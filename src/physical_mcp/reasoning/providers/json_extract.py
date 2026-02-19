"""Robust JSON extraction from LLM responses.

All vision providers share this 4-stage fallback:
  1. Strip markdown code fences (```json ... ```)
  2. Direct JSON parse
  3. Find outermost { } boundaries (handles leading/trailing noise)
  4. Truncation repair (close open brackets/braces)
"""

from __future__ import annotations

import json


def extract_json(text: str) -> dict:
    """Extract a JSON object from an LLM response string.

    Handles:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around JSON
    - Truncated JSON (unclosed brackets/braces)
    - Extra commas, noise characters

    Raises json.JSONDecodeError if no valid JSON can be extracted.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end]).strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find JSON object boundaries (handles leading/trailing noise)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Strategy 3: Truncation repair — close open brackets/braces
    if start != -1:
        fragment = text[start:].rstrip().rstrip(",")
        open_brackets = fragment.count("[") - fragment.count("]")
        fragment += "]" * max(0, open_brackets)
        open_braces = fragment.count("{") - fragment.count("}")
        fragment += "}" * max(0, open_braces)
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    # Nothing worked
    raise json.JSONDecodeError("Could not extract JSON from LLM response", text, 0)
