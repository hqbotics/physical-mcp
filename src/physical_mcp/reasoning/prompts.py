"""Provider-agnostic prompt templates for scene analysis and rule evaluation."""

from __future__ import annotations

from ..perception.scene_state import SceneState
from ..rules.models import WatchRule

_RULE_EVAL_GUIDANCE = """CRITICAL evaluation guidelines — READ CAREFULLY:

BIAS TOWARD TRIGGERING: You are a proactive alert system. Users WANT to be notified.
Missing a real event is MUCH WORSE than a false alarm. When in doubt, TRIGGER.

Action detection at 1fps (you will NOT see smooth motion):
- Drinking: person near a bottle/cup/glass = TRIGGERED. You will NOT see them swallow.
  If a person is within arm's reach of a drink AND their hand/body is oriented toward it, trigger.
- Eating: person near food with hands near mouth = TRIGGERED.
- Gestures: raised hands/arms in approximate position = TRIGGERED.
- Presence: if the rule says "when a person..." and you see a person, strongly consider triggering.

Confidence scoring:
- 0.9+ = certain match
- 0.7-0.9 = strong match (trigger)
- 0.5-0.7 = probable match (trigger)
- 0.3-0.5 = possible match (trigger with lower confidence)
- below 0.3 = unlikely

Set triggered=true for ANYTHING 0.3 or above.
FALSE NEGATIVES (missing real events) are unacceptable — users will lose trust.
FALSE POSITIVES (extra alerts) are tolerable — users can adjust rules."""


def _frame_preamble(frame_count: int) -> str:
    """Return temporal context instruction when multiple frames are provided."""
    if frame_count <= 1:
        return "Analyze this camera frame."
    return (
        f"You are given {frame_count} consecutive camera frames spanning ~1.5 seconds.\n"
        f"Frame 1 = oldest, Frame {frame_count} = most recent.\n"
        "Analyze the SEQUENCE — look for actions that happen across frames "
        "(e.g., hand raising to mouth = drinking, arm going up = waving).\n"
        "A brief action visible in even ONE frame should be detected."
    )


def build_analysis_prompt(previous_state: SceneState, question: str = "") -> str:
    """Build the scene analysis prompt."""
    context = ""
    if previous_state.summary:
        context = f"""Previous scene state:
{previous_state.to_context_string()}

Describe what changed, if anything.
"""

    question_part = ""
    if question:
        question_part = f"\nAlso answer this specific question: {question}\n"

    return f"""Analyze this camera frame. Provide a structured description.
{context}{question_part}
Respond in JSON only:
{{
  "summary": "<1-2 sentence description of the scene>",
  "objects": ["<list of notable objects visible>"],
  "people_count": <number of people visible>,
  "activity": "<what is happening in the scene>",
  "notable_changes": "<what changed from previous state, or 'none' if first frame>"
}}"""


def _format_rule_json(rule: WatchRule, hint: str = "", indent: str = "  ") -> str:
    """Format a single rule as JSON, including optional hint from self-tuning."""
    parts = f'{indent}{{"id": "{rule.id}", "condition": "{rule.condition}"'
    if hint:
        parts += f', "hint": "{hint}"'
    parts += "}"
    return parts


def build_rule_eval_prompt(
    scene_state: SceneState,
    rules: list[WatchRule],
    rule_hints: dict[str, str] | None = None,
) -> str:
    """Build the rule evaluation prompt."""
    hints = rule_hints or {}
    rules_text = "\n".join(
        _format_rule_json(r, hints.get(r.id, ""), indent="  ") for r in rules
    )

    context = ""
    if scene_state.summary:
        context = f"""Current scene context:
{scene_state.to_context_string()}

"""

    return f"""You are a visual monitoring system. Analyze the image against these watch rules.
{context}
Active watch rules:
[{rules_text}]

For EACH rule, determine if the condition is currently met in the image.
Respond in JSON only:
{{
  "evaluations": [
    {{
      "rule_id": "<id>",
      "triggered": true/false,
      "confidence": 0.0-1.0,
      "reasoning": "<brief explanation>"
    }}
  ]
}}

{_RULE_EVAL_GUIDANCE}"""


def build_combined_prompt(
    previous_state: SceneState,
    rules: list[WatchRule],
    frame_count: int = 1,
    rule_hints: dict[str, str] | None = None,
) -> str:
    """Build a single prompt that does scene analysis + rule evaluation together.

    This halves latency by making ONE LLM call instead of two sequential calls.
    When frame_count > 1, adds temporal context instructions so the LLM knows
    to look for actions across the frame sequence.

    rule_hints: optional dict mapping rule_id → short hint string from self-tuning.
    """
    context = ""
    if previous_state.summary:
        context = f"""Previous scene state:
{previous_state.to_context_string()}

"""

    hints = rule_hints or {}
    rules_text = "\n".join(
        _format_rule_json(r, hints.get(r.id, ""), indent="    ") for r in rules
    )

    preamble = _frame_preamble(frame_count)

    return f"""{preamble}

Evaluate watch rules in the same response.
{context}
Active watch rules:
[{rules_text}]

IMPORTANT: The camera may be tilted or at an unusual angle. Interpret the scene from the camera's perspective.

Respond in JSON only:
{{
  "scene": {{
    "summary": "<1-2 sentence description>",
    "objects": ["<notable objects>"],
    "people_count": <number>,
    "activity": "<what is happening>",
    "notable_changes": "<what changed or 'none'>"
  }},
  "evaluations": [
    {{
      "rule_id": "<id>",
      "triggered": true/false,
      "confidence": 0.0-1.0,
      "reasoning": "<brief explanation>"
    }}
  ]
}}

{_RULE_EVAL_GUIDANCE}"""
