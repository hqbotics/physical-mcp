"""Frame analyzer — orchestrates LLM calls through the configured provider."""

from __future__ import annotations

import asyncio
import json
import logging

from ..camera.base import Frame
from ..config import PhysicalMCPConfig
from ..perception.scene_state import SceneState
from ..rules.models import RuleEvaluation, WatchRule
from .prompts import build_analysis_prompt, build_rule_eval_prompt
from .providers.base import VisionProvider

logger = logging.getLogger("physical-mcp")

# Default maximum time to wait for an LLM API call (seconds).
# Overridden by config.reasoning.llm_timeout_seconds at runtime.
LLM_CALL_TIMEOUT = 30.0


def _is_api_error(e: Exception) -> bool:
    """Check if this is a rate-limit, auth, or billing error that should trigger backoff."""
    msg = str(e).lower()
    return any(
        keyword in msg
        for keyword in [
            "429",
            "rate",
            "quota",
            "resource_exhausted",
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "400",
            "credit",
            "balance",
            "billing",
        ]
    )


class FrameAnalyzer:
    """Multi-provider frame analysis orchestrator."""

    def __init__(self, provider: VisionProvider | None = None):
        self._provider = provider

    @property
    def has_provider(self) -> bool:
        return self._provider is not None

    @property
    def provider_info(self) -> dict:
        if self._provider is None:
            return {"configured": False}
        return {
            "configured": True,
            "provider": self._provider.provider_name,
            "model": self._provider.model_name,
        }

    def set_provider(self, provider: VisionProvider | None) -> None:
        self._provider = provider

    async def analyze_scene(
        self,
        frame: Frame,
        previous_state: SceneState,
        config: PhysicalMCPConfig,
        question: str = "",
    ) -> dict:
        """Describe what's in the frame. Returns structured scene data.

        Raises on API/rate-limit errors so the perception loop can backoff.
        Only catches JSON parse errors (retry with plain text).
        """
        if not self._provider:
            raise RuntimeError("No vision provider configured")

        prompt = build_analysis_prompt(previous_state, question)
        image_b64 = frame.to_thumbnail(
            max_dim=config.reasoning.max_thumbnail_dim,
            quality=config.reasoning.image_quality,
        )
        timeout = getattr(config.reasoning, "llm_timeout_seconds", LLM_CALL_TIMEOUT)

        try:
            return await asyncio.wait_for(
                self._provider.analyze_image_json(image_b64, prompt),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Scene analysis timed out after %.0fs", timeout)
            return {"summary": "", "objects": [], "people_count": 0}
        except json.JSONDecodeError:
            # JSON parse failure — don't retry (same response likely).
            # Return empty summary so the caller keeps the previous good scene data.
            logger.warning("Scene analysis returned unparseable JSON")
            return {"summary": "", "objects": [], "people_count": 0}
        except Exception as e:
            if _is_api_error(e):
                raise  # Let perception loop handle backoff
            logger.error("Scene analysis failed: %s", e)
            return {"summary": f"Analysis error: {e}", "objects": [], "people_count": 0}

    async def evaluate_rules(
        self,
        frame: Frame,
        scene_state: SceneState,
        rules: list[WatchRule],
        config: PhysicalMCPConfig,
    ) -> list[RuleEvaluation]:
        """Evaluate active watch rules against current frame + state.

        Raises on API/rate-limit errors so the perception loop can backoff.
        """
        if not self._provider or not rules:
            return []

        prompt = build_rule_eval_prompt(scene_state, rules)
        image_b64 = frame.to_thumbnail(
            max_dim=config.reasoning.max_thumbnail_dim,
            quality=config.reasoning.image_quality,
        )
        timeout = getattr(config.reasoning, "llm_timeout_seconds", LLM_CALL_TIMEOUT)

        try:
            raw = await asyncio.wait_for(
                self._provider.analyze_image_json(image_b64, prompt),
                timeout=timeout,
            )
            return [RuleEvaluation(**ev) for ev in raw.get("evaluations", [])]
        except asyncio.TimeoutError:
            logger.warning("Rule evaluation timed out after %.0fs", timeout)
            return []
        except Exception as e:
            if _is_api_error(e):
                raise  # Let perception loop handle backoff
            logger.error("Rule evaluation failed: %s", e)
            return []
