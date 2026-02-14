"""Tests for the markdown-based persistent memory system."""

import pytest

from physical_mcp.memory import MemoryStore


class TestMemoryStore:
    def test_read_empty(self, tmp_path):
        """Non-existent file returns empty string."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        assert store.read_all() == ""

    def test_append_event(self, tmp_path):
        """Events are appended with timestamps."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.append_event("Rule created: watch the door")
        store.append_event("ALERT: person at door")

        content = store.read_all()
        assert "Rule created: watch the door" in content
        assert "ALERT: person at door" in content

    def test_get_recent_events(self, tmp_path):
        """Returns last N events in order."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        for i in range(10):
            store.append_event(f"Event {i}")

        recent = store.get_recent_events(3)
        assert len(recent) == 3
        assert "Event 7" in recent[0]
        assert "Event 9" in recent[2]

    def test_set_rule_context(self, tmp_path):
        """Rule context is stored and retrievable."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.set_rule_context("r_123", "Watch for water running out")

        content = store.read_all()
        assert "r_123" in content
        assert "Watch for water running out" in content

    def test_set_rule_context_overwrites(self, tmp_path):
        """Setting context for same rule_id overwrites previous entry."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.set_rule_context("r_123", "Old context")
        store.set_rule_context("r_123", "New context")

        content = store.read_all()
        assert "Old context" not in content
        assert "New context" in content

    def test_remove_rule_context(self, tmp_path):
        """Removed rule context disappears from file."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.set_rule_context("r_123", "Watch for something")
        store.remove_rule_context("r_123")

        content = store.read_all()
        assert "r_123" not in content

    def test_set_preference(self, tmp_path):
        """Preferences are stored."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.set_preference("notification_style", "brief")

        content = store.read_all()
        assert "notification_style" in content
        assert "brief" in content

    def test_event_log_trimming(self, tmp_path):
        """Event log trims to max size."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        for i in range(600):
            store.append_event(f"Event {i}")

        events = store.get_recent_events(9999)
        assert len(events) == 500
        # Should keep the latest events
        assert "Event 599" in events[-1]
        assert "Event 100" in events[0]

    def test_sections_independent(self, tmp_path):
        """Events, rules, and preferences don't interfere."""
        store = MemoryStore(str(tmp_path / "memory.md"))
        store.append_event("Some event")
        store.set_rule_context("r_1", "Some rule context")
        store.set_preference("key1", "val1")

        content = store.read_all()
        assert "Some event" in content
        assert "r_1" in content
        assert "key1" in content

        # Removing rule context shouldn't affect events
        store.remove_rule_context("r_1")
        content = store.read_all()
        assert "Some event" in content
        assert "r_1" not in content
        assert "key1" in content
