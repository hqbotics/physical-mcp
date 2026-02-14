"""Frame analyzer — orchestrates LLM calls through the configured provider."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..camera.base import Frame
from ..config import PhysicalMCPConfig
from ..perception.scene_state import SceneState
from ..rules.models import RuleEvaluation, WatchRule
from .prompts import build_analysis_prompt, build_rule_eval_prompt
from .providers.base import VisionProvider

logger = logging.getLogger("physical-mcp")


def _is_api_error(e: Exception) -> bool:
    """Check if this is a rate-limit, auth, or billing error that should trigger backoff."""
    msg = str(e).lower()
    return any(keyword in msg for keyword in [
        "429", "rate", "quota", "resource_exhausted",
        "401", "403", "unauthorized", "forbidden",
        "400", "credit", "balance", "billing",
    ])


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

        try:
            return await self._provider.analyze_image_json(image_b64, prompt)
        except json.JSONDecodeError:
            # JSON parse failure — try plain text (the API worked, just bad format)
            try:
                text = await self._provider.analyze_image(image_b64, prompt)
                return {"summary": text, "objects": [], "people_count": 0}
            except Exception as e2:
                if _is_api_error(e2):
                    raise  # Let perception loop handle backoff
                logger.error(f"Scene analysis retry failed: {e2}")
                return {"summary": f"Analysis error: {e2}", "objects": [], "people_count": 0}
        except Exception as e:
            if _is_api_error(e):
                raise  # Let perception loop handle backoff
            logger.error(f"Scene analysis failed: {e}")
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

        try:
            raw = await self._provider.analyze_image_json(image_b64, prompt)
            return [
                RuleEvaluation(**ev) for ev in raw.get("evaluations", [])
            ]
        except Exception as e:
            if _is_api_error(e):
                raise  # Let perception loop handle backoff
            logger.error(f"Rule evaluation failed: {e}")
            return []
