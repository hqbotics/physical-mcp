"""Provider-agnostic prompt templates for scene analysis and rule evaluation."""

from __future__ import annotations

from ..perception.scene_state import SceneState
from ..rules.models import WatchRule


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

Be conservative. Only set triggered=true with confidence >= 0.7. False positives waste user attention."""


def build_combined_prompt(previous_state: SceneState, rules: list[WatchRule]) -> str:
    """Build a single prompt that does scene analysis + rule evaluation together.

    This halves latency by making ONE LLM call instead of two sequential calls.
    """
    context = ""
    if previous_state.summary:
        context = f"""Previous scene state:
{previous_state.to_context_string()}

"""

    rules_text = "\n".join(
        f'    {{"id": "{r.id}", "condition": "{r.condition}"}}' for r in rules
    )

    return f"""Analyze this camera frame AND evaluate watch rules in a single response.
{context}
Active watch rules:
[{rules_text}]

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

Be conservative with rules. Only triggered=true with confidence >= 0.7."""
