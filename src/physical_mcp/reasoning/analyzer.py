"""Frame analyzer — orchestrates LLM calls through the configured provider."""

from __future__ import annotations

import asyncio
import json
import logging

from ..camera.base import Frame
from ..config import PhysicalMCPConfig
from ..perception.scene_state import SceneState
from ..rules.models import RuleEvaluation, WatchRule
from .prompts import (
    build_analysis_prompt,
    build_combined_prompt,
    build_rule_eval_prompt,
)
from .providers.base import VisionProvider

logger = logging.getLogger("physical-mcp")

# Default maximum time to wait for an LLM API call (seconds).
# Overridden by config.reasoning.llm_timeout_seconds at runtime.
LLM_CALL_TIMEOUT = 15.0


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


def _encode_frames(frames: list[Frame], config: PhysicalMCPConfig) -> list[str]:
    """Encode a list of frames to base64 thumbnails."""
    return [
        f.to_thumbnail(
            max_dim=config.reasoning.max_thumbnail_dim,
            quality=config.reasoning.image_quality,
        )
        for f in frames
    ]


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

    async def warmup(self) -> None:
        """Pre-establish API connection to reduce first-call latency."""
        if self._provider:
            await self._provider.warmup()

    async def analyze_scene(
        self,
        frame: Frame | list[Frame],
        previous_state: SceneState,
        config: PhysicalMCPConfig,
        question: str = "",
    ) -> dict:
        """Describe what's in the frame(s). Returns structured scene data.

        Accepts a single Frame or list of Frames for multi-frame temporal analysis.
        Raises on API/rate-limit errors so the perception loop can backoff.
        """
        if not self._provider:
            raise RuntimeError("No vision provider configured")

        frames = frame if isinstance(frame, list) else [frame]
        prompt = build_analysis_prompt(previous_state, question)
        images_b64 = _encode_frames(frames, config)
        timeout = getattr(config.reasoning, "llm_timeout_seconds", LLM_CALL_TIMEOUT)

        try:
            return await asyncio.wait_for(
                self._provider.analyze_images_json(images_b64, prompt),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Scene analysis timed out after %.0fs", timeout)
            return {"summary": "", "objects": [], "people_count": 0}
        except json.JSONDecodeError:
            logger.warning("Scene analysis returned unparseable JSON")
            return {"summary": "", "objects": [], "people_count": 0}
        except Exception as e:
            if _is_api_error(e):
                raise
            logger.error("Scene analysis failed: %s", e)
            return {"summary": f"Analysis error: {e}", "objects": [], "people_count": 0}

    async def answer_question(
        self,
        frame: Frame | list[Frame],
        previous_state: SceneState,
        question: str,
        config: PhysicalMCPConfig,
    ) -> str:
        """Answer a free-text question about what the camera sees.

        Returns a natural language answer string.
        Uses analyze_scene with the question parameter to get a contextual response.
        """
        if not self._provider:
            return "No vision provider configured. Set one up with 'physical-mcp setup --advanced'."

        try:
            result = await self.analyze_scene(
                frame, previous_state, config, question=question
            )
            summary = result.get("summary", "")
            if summary and not summary.startswith("Analysis error:"):
                return summary
            return f"I can see the scene but couldn't answer specifically. Current scene: {previous_state.summary or 'no data yet'}"
        except Exception as e:
            logger.error("answer_question failed: %s", e)
            if previous_state.summary:
                return f"Couldn't analyze right now, but last I saw: {previous_state.summary}"
            return f"Sorry, I couldn't analyze the scene right now: {e}"

    async def analyze_and_evaluate(
        self,
        frame: Frame | list[Frame],
        scene_state: SceneState,
        rules: list[WatchRule],
        config: PhysicalMCPConfig,
    ) -> dict:
        """Combined scene analysis + rule evaluation in ONE LLM call.

        Accepts a single Frame or list of Frames for multi-frame temporal analysis.
        Returns {"scene": {...}, "evaluations": [RuleEvaluation, ...]}.

        Raises on API/rate-limit errors so the perception loop can backoff.
        """
        if not self._provider:
            raise RuntimeError("No vision provider configured")

        frames = frame if isinstance(frame, list) else [frame]

        if not rules:
            scene_data = await self.analyze_scene(frames, scene_state, config)
            return {"scene": scene_data, "evaluations": []}

        prompt = build_combined_prompt(scene_state, rules, frame_count=len(frames))
        images_b64 = _encode_frames(frames, config)
        timeout = getattr(config.reasoning, "llm_timeout_seconds", LLM_CALL_TIMEOUT)

        try:
            raw = await asyncio.wait_for(
                self._provider.analyze_images_json(images_b64, prompt),
                timeout=timeout,
            )
            scene_data = raw.get("scene", {})
            evals_raw = raw.get("evaluations", [])
            evaluations = [RuleEvaluation(**ev) for ev in evals_raw]
            return {"scene": scene_data, "evaluations": evaluations}
        except asyncio.TimeoutError:
            logger.warning("Combined analysis timed out after %.0fs", timeout)
            return {
                "scene": {"summary": "", "objects": [], "people_count": 0},
                "evaluations": [],
            }
        except json.JSONDecodeError:
            logger.warning("Combined analysis returned unparseable JSON")
            return {
                "scene": {"summary": "", "objects": [], "people_count": 0},
                "evaluations": [],
            }
        except Exception as e:
            if _is_api_error(e):
                raise
            logger.error("Combined analysis failed: %s", e)
            return {
                "scene": {
                    "summary": f"Analysis error: {e}",
                    "objects": [],
                    "people_count": 0,
                },
                "evaluations": [],
            }

    async def evaluate_rules(
        self,
        frame: Frame | list[Frame],
        scene_state: SceneState,
        rules: list[WatchRule],
        config: PhysicalMCPConfig,
    ) -> list[RuleEvaluation]:
        """Evaluate active watch rules against current frame(s) + state.

        Accepts a single Frame or list of Frames for multi-frame temporal analysis.
        Raises on API/rate-limit errors so the perception loop can backoff.
        """
        if not self._provider or not rules:
            return []

        frames = frame if isinstance(frame, list) else [frame]
        prompt = build_rule_eval_prompt(scene_state, rules)
        images_b64 = _encode_frames(frames, config)
        timeout = getattr(config.reasoning, "llm_timeout_seconds", LLM_CALL_TIMEOUT)

        try:
            raw = await asyncio.wait_for(
                self._provider.analyze_images_json(images_b64, prompt),
                timeout=timeout,
            )
            return [RuleEvaluation(**ev) for ev in raw.get("evaluations", [])]
        except asyncio.TimeoutError:
            logger.warning("Rule evaluation timed out after %.0fs", timeout)
            return []
        except Exception as e:
            if _is_api_error(e):
                raise
            logger.error("Rule evaluation failed: %s", e)
            return []
