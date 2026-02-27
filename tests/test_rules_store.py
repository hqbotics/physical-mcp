"""Tests for YAML rules persistence (RulesStore)."""

from __future__ import annotations


from physical_mcp.rules.models import NotificationTarget, RulePriority, WatchRule
from physical_mcp.rules.store import RulesStore


def _make_rule(
    id: str = "r_test1",
    name: str = "Test Rule",
    condition: str = "a person is visible",
    priority: str = "high",
    custom_message: str | None = None,
) -> WatchRule:
    return WatchRule(
        id=id,
        name=name,
        condition=condition,
        priority=RulePriority(priority),
        notification=NotificationTarget(type="local"),
        custom_message=custom_message,
    )


class TestRulesStore:
    """RulesStore YAML save/load roundtrip."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """Rules survive a save→load roundtrip."""
        path = tmp_path / "rules.yaml"
        store = RulesStore(str(path))
        rules = [_make_rule("r_1", "Rule A"), _make_rule("r_2", "Rule B")]
        store.save(rules)
        loaded = store.load()
        assert len(loaded) == 2
        assert loaded[0].id == "r_1"
        assert loaded[0].name == "Rule A"
        assert loaded[1].id == "r_2"

    def test_load_nonexistent_file(self, tmp_path):
        """Loading from nonexistent file returns empty list."""
        store = RulesStore(str(tmp_path / "missing.yaml"))
        assert store.load() == []

    def test_load_empty_file(self, tmp_path):
        """Loading from empty file returns empty list."""
        path = tmp_path / "empty.yaml"
        path.write_text("")
        store = RulesStore(str(path))
        assert store.load() == []

    def test_load_corrupted_yaml(self, tmp_path):
        """Loading corrupted YAML returns empty list (no crash)."""
        path = tmp_path / "bad.yaml"
        path.write_text("{{{{not valid yaml!!!!")
        store = RulesStore(str(path))
        assert store.load() == []

    def test_load_yaml_without_rules_key(self, tmp_path):
        """YAML with no 'rules' key returns empty list."""
        path = tmp_path / "norules.yaml"
        path.write_text("something_else:\n  - foo\n")
        store = RulesStore(str(path))
        assert store.load() == []

    def test_save_creates_parent_dirs(self, tmp_path):
        """Save creates parent directories if needed."""
        path = tmp_path / "deep" / "nested" / "rules.yaml"
        store = RulesStore(str(path))
        store.save([_make_rule()])
        assert path.exists()
        loaded = store.load()
        assert len(loaded) == 1

    def test_custom_message_persists(self, tmp_path):
        """Custom message survives roundtrip."""
        path = tmp_path / "rules.yaml"
        store = RulesStore(str(path))
        rule = _make_rule(custom_message="Watch out!")
        store.save([rule])
        loaded = store.load()
        assert loaded[0].custom_message == "Watch out!"

    def test_save_overwrites_existing(self, tmp_path):
        """Second save replaces previous rules."""
        path = tmp_path / "rules.yaml"
        store = RulesStore(str(path))
        store.save([_make_rule("r_1"), _make_rule("r_2")])
        store.save([_make_rule("r_3")])
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].id == "r_3"

    def test_save_empty_list(self, tmp_path):
        """Saving empty list writes valid YAML that loads as empty."""
        path = tmp_path / "rules.yaml"
        store = RulesStore(str(path))
        store.save([_make_rule()])
        store.save([])
        assert store.load() == []

    def test_notification_fields_persist(self, tmp_path):
        """Notification target fields survive roundtrip."""
        path = tmp_path / "rules.yaml"
        store = RulesStore(str(path))
        rule = WatchRule(
            id="r_notif",
            name="Telegram Rule",
            condition="person detected",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(
                type="telegram",
                target="12345",
                channel="chat",
            ),
        )
        store.save([rule])
        loaded = store.load()
        assert loaded[0].notification.type == "telegram"
        assert loaded[0].notification.target == "12345"

    def test_tilde_path_expansion(self, tmp_path, monkeypatch):
        """Tilde paths are expanded correctly."""
        monkeypatch.setenv("HOME", str(tmp_path))
        store = RulesStore("~/test-rules.yaml")
        store.save([_make_rule()])
        loaded = store.load()
        assert len(loaded) == 1
