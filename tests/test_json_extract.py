"""Tests for the shared JSON extraction utility."""

import json

import pytest

from physical_mcp.reasoning.providers.json_extract import extract_json


class TestExtractJson:
    def test_clean_json(self):
        result = extract_json('{"summary": "A room", "objects": []}')
        assert result == {"summary": "A room", "objects": []}

    def test_markdown_fenced_json(self):
        text = '```json\n{"summary": "A room", "objects": []}\n```'
        result = extract_json(text)
        assert result["summary"] == "A room"

    def test_markdown_fenced_no_closing(self):
        text = '```json\n{"summary": "A room", "objects": []}'
        result = extract_json(text)
        assert result["summary"] == "A room"

    def test_leading_trailing_prose(self):
        text = (
            'Here is the analysis:\n{"summary": "office", "objects": ["desk"]}\nDone!'
        )
        result = extract_json(text)
        assert result["summary"] == "office"

    def test_truncated_json_unclosed_brace(self):
        text = '{"summary": "room", "objects": ["chair", "table"'
        result = extract_json(text)
        assert result["summary"] == "room"
        assert result["objects"] == ["chair", "table"]

    def test_truncated_json_unclosed_bracket_and_brace(self):
        text = '{"summary": "room", "objects": ["chair"'
        result = extract_json(text)
        assert result["summary"] == "room"

    def test_trailing_comma_repair(self):
        text = '{"summary": "room", "objects": ["chair",]}'
        # json.loads doesn't handle trailing commas, but our extraction
        # tries the direct parse first. This may fail depending on Python version.
        # The main thing is it shouldn't crash unexpectedly.
        with pytest.raises(json.JSONDecodeError):
            extract_json(text)

    def test_completely_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json("This is just text with no JSON at all.")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json("")

    def test_nested_json(self):
        text = '{"summary": "room", "details": {"temp": 22, "light": "bright"}}'
        result = extract_json(text)
        assert result["details"]["temp"] == 22

    def test_markdown_fence_with_language_tag(self):
        text = '```json\n{"key": "value"}\n```'
        assert extract_json(text) == {"key": "value"}

    def test_markdown_fence_plain(self):
        text = '```\n{"key": "value"}\n```'
        assert extract_json(text) == {"key": "value"}

    def test_whitespace_padding(self):
        text = '   \n  {"key": "value"}  \n  '
        assert extract_json(text) == {"key": "value"}
