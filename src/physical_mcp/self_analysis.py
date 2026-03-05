"""Self-analysis and self-tuning for watch rule accuracy.

Periodically reviews the evaluation log, identifies false positive/negative
patterns, and adjusts per-rule confidence thresholds and prompt hints.
"""

from __future__ import annotations

import asyncio
import logging

from .eval_log import EvalLog
from .reasoning.analyzer import FrameAnalyzer

logger = logging.getLogger("physical-mcp")

_ANALYSIS_PROMPT = """You are analyzing the accuracy of a camera watch rule.

Rule: "{condition}"
Rule ID: {rule_id}

Recent evaluation statistics (last {window_hours} hours):
- Total evaluations: {total_evals}
- Times triggered (alert sent): {triggered_count}
- User feedback received: {feedback_count}
  - Correct (true positive): {tp_count}
  - Wrong (false positive): {fp_count}
  - Missed events (false negative): {fn_count}
- Current confidence threshold: {current_threshold}
- Current prompt hint: "{current_hint}"

Sample evaluations (most recent first):
{eval_samples}

Respond in JSON only:
{{
  "accuracy_assessment": "<1-2 sentences>",
  "false_positive_pattern": "<what FPs have in common, or 'none'>",
  "false_negative_pattern": "<what FNs have in common, or 'none'>",
  "recommended_threshold": <float 0.1-0.9>,
  "recommended_hint": "<short hint for the LLM to reduce errors, max 100 chars, or empty string>",
  "reasoning": "<why these changes will help>"
}}

Guidelines:
- If accuracy > 80%, keep threshold the same.
- Many false positives → RAISE threshold (e.g., 0.3 → 0.5).
- Many false negatives → LOWER threshold (e.g., 0.3 → 0.2).
- Hint should address the specific confusion pattern.
  Example: "Phone near face is NOT drinking"
- Be conservative. Max threshold change of 0.15 per analysis."""


class SelfAnalyzer:
    """Analyzes evaluation logs and tunes per-rule settings."""

    def __init__(self, eval_log: EvalLog, analyzer: FrameAnalyzer):
        self._eval_log = eval_log
        self._analyzer = analyzer

    async def analyze_rule(self, rule_id: str, window_hours: int = 24) -> dict:
        """Analyze a single rule's accuracy.  Returns result dict."""
        stats = self._eval_log.get_rule_stats(rule_id)
        recent = self._eval_log.get_recent_evals(rule_id, hours=window_hours, limit=50)

        if not recent:
            return {"rule_id": rule_id, "skipped": True, "reason": "no evaluations"}

        total = len(recent)
        triggered = sum(1 for e in recent if e["triggered"])
        with_feedback = [e for e in recent if e.get("feedback")]
        tp = sum(
            1 for e in with_feedback if e["feedback"] == "correct" and e["triggered"]
        )
        fp = sum(
            1 for e in with_feedback if e["feedback"] == "wrong" and e["triggered"]
        )
        fn = sum(1 for e in with_feedback if e["feedback"] == "missed")

        current_threshold = stats["confidence_threshold"] if stats else 0.3
        current_hint = stats["prompt_hint"] if stats else ""

        if len(with_feedback) < 5:
            return {
                "rule_id": rule_id,
                "skipped": True,
                "reason": f"only {len(with_feedback)} feedback items (need 5+)",
                "stats": {
                    "total": total,
                    "triggered": triggered,
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                },
            }

        samples = []
        for e in recent[:15]:
            fb = e.get("feedback", "no feedback")
            samples.append(
                f"  - triggered={bool(e['triggered'])}, conf={e['confidence']:.2f}, "
                f"feedback={fb}, reasoning={e['reasoning'][:80]}"
            )
        eval_samples = "\n".join(samples) if samples else "(no evaluations)"

        if not self._analyzer.has_provider:
            return {
                "rule_id": rule_id,
                "skipped": True,
                "reason": "no LLM provider",
            }

        prompt = _ANALYSIS_PROMPT.format(
            condition=recent[0].get("condition", ""),
            rule_id=rule_id,
            window_hours=window_hours,
            total_evals=total,
            triggered_count=triggered,
            feedback_count=len(with_feedback),
            tp_count=tp,
            fp_count=fp,
            fn_count=fn,
            current_threshold=current_threshold,
            current_hint=current_hint,
            eval_samples=eval_samples,
        )

        try:
            result = await asyncio.wait_for(
                self._analyzer._provider.analyze_images_json([], prompt),
                timeout=20.0,
            )
        except Exception as e:
            logger.error(f"Self-analysis LLM call failed for {rule_id}: {e}")
            return {"rule_id": rule_id, "error": str(e)}

        new_threshold = result.get("recommended_threshold", current_threshold)
        new_hint = result.get("recommended_hint", current_hint)

        # Safety clamp: max 0.15 change per analysis, bounded [0.1, 0.9]
        if abs(new_threshold - current_threshold) > 0.15:
            new_threshold = (
                current_threshold + 0.15
                if new_threshold > current_threshold
                else current_threshold - 0.15
            )
        new_threshold = max(0.1, min(0.9, round(new_threshold, 2)))

        self._eval_log.update_rule_tuning(
            rule_id, threshold=new_threshold, hint=new_hint
        )

        run = {
            "rule_id": rule_id,
            "window_hours": window_hours,
            "total_evals": total,
            "triggered": triggered,
            "feedback_count": len(with_feedback),
            "fp_count": fp,
            "fn_count": fn,
            "old_threshold": current_threshold,
            "new_threshold": new_threshold,
            "old_hint": current_hint,
            "new_hint": new_hint,
            "llm_reasoning": result.get("reasoning", ""),
        }
        self._eval_log.save_analysis_run(run)

        logger.info(
            f"Self-analysis {rule_id}: threshold {current_threshold:.2f} -> "
            f"{new_threshold:.2f}, hint='{new_hint}'"
        )

        return {
            "rule_id": rule_id,
            "assessment": result.get("accuracy_assessment", ""),
            "fp_pattern": result.get("false_positive_pattern", ""),
            "fn_pattern": result.get("false_negative_pattern", ""),
            "threshold_change": f"{current_threshold:.2f} -> {new_threshold:.2f}",
            "hint_change": f"'{current_hint}' -> '{new_hint}'",
            "reasoning": result.get("reasoning", ""),
        }

    async def analyze_all_rules(
        self, rule_ids: list[str], window_hours: int = 24
    ) -> list[dict]:
        """Analyze all active rules sequentially."""
        results = []
        for rid in rule_ids:
            result = await self.analyze_rule(rid, window_hours)
            results.append(result)
        return results
