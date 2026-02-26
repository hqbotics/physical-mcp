"""Provider-agnostic prompt templates for scene analysis and rule evaluation."""

from __future__ import annotations

from ..perception.scene_state import SceneState
from ..rules.models import WatchRule

_STRICT_EVAL = """Evaluate STRICTLY. Only trigger a rule if you see clear, unambiguous visual evidence.
- For gesture rules (waving, pointing): raised hands/arms must be clearly visible
- For action rules (drinking, eating, etc.): the person must be ACTIVELY performing the action, not just near an object
- A water bottle visible near someone does NOT mean they are drinking
- Confidence 0.9+ = certain, 0.7-0.9 = likely, below 0.7 = do not trigger
- When in doubt, set triggered=false. Missing an event is better than a false alert."""


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


def build_rule_eval_prompt(scene_state: SceneState, rules: list[WatchRule]) -> str:
    """Build the rule evaluation prompt."""
    rules_text = "\n".join(
        f'  {{"id": "{r.id}", "condition": "{r.condition}"}}' for r in rules
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

{_STRICT_EVAL}"""


def build_combined_prompt(
    previous_state: SceneState,
    rules: list[WatchRule],
    frame_count: int = 1,
) -> str:
    """Build a single prompt that does scene analysis + rule evaluation together.

    This halves latency by making ONE LLM call instead of two sequential calls.
    When frame_count > 1, adds temporal context instructions so the LLM knows
    to look for actions across the frame sequence.
    """
    context = ""
    if previous_state.summary:
        context = f"""Previous scene state:
{previous_state.to_context_string()}

"""

    rules_text = "\n".join(
        f'    {{"id": "{r.id}", "condition": "{r.condition}"}}' for r in rules
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

{_STRICT_EVAL}"""
