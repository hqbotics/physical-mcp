"""Pre-built rule templates for common monitoring scenarios.

Provides ready-to-use rule presets so users can pick from a menu
instead of writing natural language conditions from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleTemplate:
    """A pre-defined watch rule template."""

    id: str
    name: str
    description: str
    category: str
    condition: str
    priority: str  # "low" | "medium" | "high" | "critical"
    cooldown_seconds: int
    icon: str  # Emoji for display


# ── Built-in templates ────────────────────────────────────────────
TEMPLATES: list[RuleTemplate] = [
    # ── Security ──────────────────────────────────────────────────
    RuleTemplate(
        id="person-detection",
        name="Person Detection",
        description="Alert when any person appears in the camera view",
        category="security",
        condition="A person or human figure is visible in the camera frame",
        priority="high",
        cooldown_seconds=60,
        icon="🚶",
    ),
    RuleTemplate(
        id="person-at-door",
        name="Person at Door",
        description="Alert when someone approaches or stands at a door",
        category="security",
        condition="A person is standing at, approaching, or knocking on a door",
        priority="high",
        cooldown_seconds=60,
        icon="🚪",
    ),
    RuleTemplate(
        id="package-delivered",
        name="Package Delivered",
        description="Alert when a package or delivery is left at the door",
        category="security",
        condition="A package, box, or delivery parcel has been placed near the door or on the ground",
        priority="medium",
        cooldown_seconds=300,
        icon="📦",
    ),
    RuleTemplate(
        id="unusual-activity",
        name="Unusual Activity",
        description="Alert on anything out of the ordinary",
        category="security",
        condition="Something unusual, unexpected, or out of the ordinary is happening in the scene",
        priority="high",
        cooldown_seconds=120,
        icon="⚠️",
    ),
    # ── Pet Monitoring ────────────────────────────────────────────
    RuleTemplate(
        id="pet-on-furniture",
        name="Pet on Furniture",
        description="Alert when a pet climbs on furniture (couch, bed, table)",
        category="pets",
        condition="A pet (dog or cat) is on the couch, sofa, bed, table, or other furniture",
        priority="medium",
        cooldown_seconds=120,
        icon="🐾",
    ),
    RuleTemplate(
        id="pet-at-door",
        name="Pet at Door",
        description="Alert when a pet is waiting at the door (wants to go out)",
        category="pets",
        condition="A pet (dog or cat) is sitting or standing near the door, appearing to want to go outside",
        priority="medium",
        cooldown_seconds=180,
        icon="🐕",
    ),
    # ── Family Safety ─────────────────────────────────────────────
    RuleTemplate(
        id="baby-monitor",
        name="Baby Monitor",
        description="Alert when baby is crying, standing in crib, or in distress",
        category="family",
        condition="A baby or toddler appears to be crying, in distress, standing up in the crib, or has left the crib",
        priority="critical",
        cooldown_seconds=30,
        icon="👶",
    ),
    RuleTemplate(
        id="child-safety",
        name="Child Safety",
        description="Alert when a child approaches a restricted area",
        category="family",
        condition="A child is approaching or entering a restricted, dangerous, or off-limits area such as stairs, kitchen stove, pool, or front door",
        priority="critical",
        cooldown_seconds=30,
        icon="🧒",
    ),
    RuleTemplate(
        id="elderly-fall",
        name="Elderly Fall Detection",
        description="Alert when an elderly person falls or is on the ground",
        category="family",
        condition="A person appears to have fallen down, is lying on the floor, or is in a position suggesting they may need help",
        priority="critical",
        cooldown_seconds=30,
        icon="🆘",
    ),
    # ── Home Automation ───────────────────────────────────────────
    RuleTemplate(
        id="motion-alert",
        name="Motion Alert",
        description="Alert on any significant movement in the scene",
        category="automation",
        condition="There is significant movement or motion in the scene compared to a static background",
        priority="low",
        cooldown_seconds=60,
        icon="🔔",
    ),
    RuleTemplate(
        id="lights-left-on",
        name="Lights Left On",
        description="Alert when lights are left on in an empty room",
        category="automation",
        condition="The room lights are on but no person is visible in the room",
        priority="low",
        cooldown_seconds=600,
        icon="💡",
    ),
    RuleTemplate(
        id="stove-check",
        name="Stove Safety Check",
        description="Alert when the stove or oven appears to be on unattended",
        category="automation",
        condition="A stove burner or oven appears to be on or active, but no person is in the kitchen attending to it",
        priority="critical",
        cooldown_seconds=120,
        icon="🔥",
    ),
    # ── Business / Retail ─────────────────────────────────────────
    RuleTemplate(
        id="customer-entered",
        name="Customer Entered",
        description="Alert when a customer enters the store or area",
        category="business",
        condition="A person has just entered the store, shop, or monitored area through the entrance",
        priority="medium",
        cooldown_seconds=30,
        icon="🏪",
    ),
    RuleTemplate(
        id="crowding-alert",
        name="Crowding Alert",
        description="Alert when too many people gather in one area",
        category="business",
        condition="There are more than 5 people gathered in the same area, suggesting crowding",
        priority="high",
        cooldown_seconds=300,
        icon="👥",
    ),
]

# Index for fast lookup
_TEMPLATES_BY_ID: dict[str, RuleTemplate] = {t.id: t for t in TEMPLATES}


def list_templates(category: str | None = None) -> list[RuleTemplate]:
    """Return all templates, optionally filtered by category."""
    if category:
        return [t for t in TEMPLATES if t.category == category]
    return list(TEMPLATES)


def get_template(template_id: str) -> RuleTemplate | None:
    """Look up a template by ID."""
    return _TEMPLATES_BY_ID.get(template_id)


def get_categories() -> list[str]:
    """Return sorted list of unique categories."""
    return sorted({t.category for t in TEMPLATES})
