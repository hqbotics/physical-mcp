"""Tests for pre-built rule templates."""

from physical_mcp.rules.templates import (
    TEMPLATES,
    get_categories,
    get_template,
    list_templates,
)


class TestRuleTemplates:
    def test_templates_not_empty(self):
        assert len(TEMPLATES) > 0

    def test_all_templates_have_required_fields(self):
        for t in TEMPLATES:
            assert t.id, f"Template missing id: {t}"
            assert t.name, f"Template missing name: {t.id}"
            assert t.description, f"Template missing description: {t.id}"
            assert t.category, f"Template missing category: {t.id}"
            assert t.condition, f"Template missing condition: {t.id}"
            assert t.priority in ("low", "medium", "high", "critical"), (
                f"Invalid priority for {t.id}: {t.priority}"
            )
            assert t.cooldown_seconds > 0, (
                f"Invalid cooldown for {t.id}: {t.cooldown_seconds}"
            )
            assert t.icon, f"Template missing icon: {t.id}"

    def test_template_ids_unique(self):
        ids = [t.id for t in TEMPLATES]
        assert len(ids) == len(set(ids)), "Duplicate template IDs found"

    def test_list_templates_returns_all(self):
        result = list_templates()
        assert len(result) == len(TEMPLATES)

    def test_list_templates_by_category(self):
        security = list_templates("security")
        assert len(security) > 0
        assert all(t.category == "security" for t in security)

    def test_list_templates_unknown_category(self):
        result = list_templates("nonexistent")
        assert result == []

    def test_get_template_found(self):
        t = get_template("person-detection")
        assert t is not None
        assert t.name == "Person Detection"
        assert t.priority == "high"

    def test_get_template_not_found(self):
        assert get_template("does-not-exist") is None

    def test_get_categories(self):
        cats = get_categories()
        assert isinstance(cats, list)
        assert "security" in cats
        assert "pets" in cats
        assert "family" in cats
        assert "automation" in cats
        # Should be sorted
        assert cats == sorted(cats)

    def test_specific_templates_exist(self):
        """Ensure key consumer templates are present."""
        expected_ids = [
            "person-detection",
            "person-at-door",
            "package-delivered",
            "pet-on-furniture",
            "baby-monitor",
            "motion-alert",
        ]
        for tid in expected_ids:
            assert get_template(tid) is not None, f"Missing template: {tid}"

    def test_critical_templates_have_short_cooldown(self):
        """Critical rules should respond fast."""
        for t in TEMPLATES:
            if t.priority == "critical":
                assert t.cooldown_seconds <= 120, (
                    f"Critical template {t.id} has too long cooldown: "
                    f"{t.cooldown_seconds}s"
                )
