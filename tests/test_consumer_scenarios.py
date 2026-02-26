"""Consumer scenario tests -- non-tech user workflows.

These tests simulate what real users experience when they say things like
"watch for me standing up" on Telegram, WhatsApp, or Slack via OpenClaw.
Each test validates that the system behaves correctly for a consumer:
no spam, correct alerts, graceful failures.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import tempfile

import pytest

from physical_mcp.notifications.openclaw import OpenClawNotifier
from physical_mcp.notifications import NotificationDispatcher
from physical_mcp.config import NotificationsConfig
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import (
    AlertEvent,
    NotificationTarget,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)
from physical_mcp.rules.store import RulesStore


def _make_rule(
    id: str = "r1",
    cooldown: int = 60,
    notif_type: str = "openclaw",
    channel: str = "telegram",
    target: str = "123456",
    enabled: bool = True,
) -> WatchRule:
    return WatchRule(
        id=id,
        name=f"Rule {id}",
        condition="no person visible at desk",
        priority=RulePriority.HIGH,
        notification=NotificationTarget(
            type=notif_type,
            channel=channel,
            target=target,
        ),
        cooldown_seconds=cooldown,
        enabled=enabled,
    )


def _make_eval(
    rule_id: str = "r1",
    triggered: bool = True,
    confidence: float = 0.9,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        triggered=triggered,
        confidence=confidence,
        reasoning="The desk is empty, person stood up",
    )


def _make_alert() -> AlertEvent:
    """Create a test alert event."""
    return AlertEvent(
        rule=_make_rule("r_test"),
        evaluation=_make_eval(rule_id="r_test"),
        scene_summary="Empty desk with monitor",
    )


class TestSingleAlertOnTrigger:
    """User says 'watch for me standing up' -> gets exactly ONE alert."""

    def test_single_alert_on_trigger(self):
        """Rule triggers once -> exactly one alert event generated."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState(summary="Empty desk")
        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1
        assert alerts[0].rule.id == "r1"
        assert alerts[0].evaluation.reasoning == "The desk is empty, person stood up"


class TestSilenceBetweenTriggers:
    """Between triggers, ZERO notifications sent."""

    def test_no_alert_when_not_triggered(self):
        """Condition not met -> zero alerts (no 'Still seated.' spam)."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState(summary="Person at desk")

        # Simulate 10 perception loop iterations where condition is NOT met
        for _ in range(10):
            evals = [_make_eval(triggered=False)]
            alerts = engine.process_evaluations(evals, scene)
            assert len(alerts) == 0

    def test_low_confidence_no_alert(self):
        """LLM returns 0.5 confidence -> no notification sent."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval(confidence=0.5)], scene)
        assert len(alerts) == 0


class TestAlternatingState:
    """Stand up, sit down, stand up -> alert each time (after cooldown)."""

    def test_alternating_state_with_cooldown(self):
        """Triggered -> cooldown expires -> triggered again = two alerts total."""
        engine = RulesEngine()
        rule = _make_rule("r1", cooldown=60)
        engine.add_rule(rule)
        scene = SceneState()

        # First trigger
        alerts1 = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts1) == 1

        # Simulate cooldown expired by adjusting last_triggered
        rule.last_triggered = datetime.now() - timedelta(seconds=61)

        # Second trigger
        alerts2 = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts2) == 1

    def test_no_double_alert_within_cooldown(self):
        """Two triggers within cooldown window = only one alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1", cooldown=60))
        scene = SceneState()

        alerts1 = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts1) == 1

        # Immediately trigger again -- should be blocked by cooldown
        alerts2 = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts2) == 0

    def test_cooldown_expired_allows_retrigger(self):
        """After cooldown expires, new trigger is allowed."""
        engine = RulesEngine()
        rule = _make_rule("r1", cooldown=30)
        engine.add_rule(rule)
        scene = SceneState()

        engine.process_evaluations([_make_eval()], scene)

        # Fast-forward past cooldown
        rule.last_triggered = datetime.now() - timedelta(seconds=31)

        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1


class TestCameraGracefulDegradation:
    """Laptop lid closed -> graceful handling (no crash)."""

    @pytest.mark.asyncio
    async def test_openclaw_notifier_with_empty_scene(self):
        """Alert with empty scene summary still sends message."""
        notifier = OpenClawNotifier(
            default_channel="telegram",
            default_target="123",
        )
        rule = _make_rule("r1")
        evaluation = _make_eval()
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(alert)
        assert result is True


class TestRulesPersistence:
    """Rules persist across restart."""

    def test_rules_persist_to_yaml_and_reload(self):
        """RulesStore save -> load round-trip preserves rules."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        store = RulesStore(path)
        rule1 = _make_rule(
            "r1", notif_type="openclaw", channel="telegram", target="123"
        )
        rule2 = _make_rule("r2", notif_type="desktop")

        store.save([rule1, rule2])

        loaded = store.load()
        assert len(loaded) == 2
        ids = {r.id for r in loaded}
        assert "r1" in ids
        assert "r2" in ids

        # Check notification fields preserved
        r1_loaded = next(r for r in loaded if r.id == "r1")
        assert r1_loaded.notification.type == "openclaw"
        assert r1_loaded.notification.channel == "telegram"

    def test_rules_loaded_into_engine(self):
        """Engine loads rules from store at startup."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        store = RulesStore(path)
        store.save([_make_rule("r1")])

        engine = RulesEngine()
        engine.load_rules(store.load())
        assert len(engine.list_rules()) == 1


class TestMultipleRules:
    """Two rules simultaneously: 'watch door' + 'watch desk'."""

    def test_two_rules_independent_triggers(self):
        """Rule A triggers, Rule B doesn't -> only A alert sent."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        engine.add_rule(_make_rule("r2"))
        scene = SceneState()

        evals = [
            _make_eval(rule_id="r1", triggered=True, confidence=0.9),
            _make_eval(rule_id="r2", triggered=False, confidence=0.3),
        ]
        alerts = engine.process_evaluations(evals, scene)
        assert len(alerts) == 1
        assert alerts[0].rule.id == "r1"

    def test_both_rules_trigger_simultaneously(self):
        """Both conditions met -> both alerts sent."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        engine.add_rule(_make_rule("r2"))
        scene = SceneState()

        evals = [
            _make_eval(rule_id="r1", triggered=True, confidence=0.9),
            _make_eval(rule_id="r2", triggered=True, confidence=0.85),
        ]
        alerts = engine.process_evaluations(evals, scene)
        assert len(alerts) == 2


class TestRuleManagement:
    """CRUD operations on rules."""

    def test_delete_rule_removes_it(self):
        """Remove rule -> no longer in engine."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        assert engine.remove_rule("r1") is True
        assert len(engine.list_rules()) == 0

    def test_deleted_rule_cannot_trigger(self):
        """Deleted rule ID in evaluation -> no alert."""
        engine = RulesEngine()
        engine.add_rule(_make_rule("r1"))
        engine.remove_rule("r1")
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval(rule_id="r1")], scene)
        assert len(alerts) == 0

    def test_toggle_off_stops_alerts(self):
        """Disabled rule -> condition met but no alert."""
        engine = RulesEngine()
        rule = _make_rule("r1", enabled=True)
        engine.add_rule(rule)
        assert len(engine.get_active_rules()) == 1

        rule.enabled = False
        assert len(engine.get_active_rules()) == 0

        # Evaluation still tries but rule is not found in active rules
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval()], scene)
        # Rule exists but is disabled -- engine should skip
        assert len(alerts) == 0

    def test_toggle_on_resumes_alerts(self):
        """Re-enable rule -> alerts resume."""
        engine = RulesEngine()
        rule = _make_rule("r1")
        rule.enabled = False
        engine.add_rule(rule)
        assert len(engine.get_active_rules()) == 0

        rule.enabled = True
        assert len(engine.get_active_rules()) == 1

        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval()], scene)
        assert len(alerts) == 1


class TestCrossChannel:
    """Same rule creation works for all OpenClaw channel types."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "channel,target",
        [
            ("telegram", "123456789"),
            ("whatsapp", "+8613800138000"),
            ("discord", "1167896182991896629"),
            ("slack", "channel:C0AEXJNGKAB"),
        ],
    )
    async def test_openclaw_channel_routing(self, channel, target):
        """notification_type='openclaw' routes to the correct channel."""
        notifier = OpenClawNotifier(
            default_channel=channel,
            default_target=target,
        )
        alert = _make_alert()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            result = await notifier.notify(alert)

        assert result is True
        call_args = mock_exec.call_args[0]
        idx = call_args.index("--channel")
        assert call_args[idx + 1] == channel
        idx = call_args.index("--target")
        assert call_args[idx + 1] == target


class TestDispatcherRouting:
    """NotificationDispatcher correctly routes openclaw type."""

    @pytest.mark.asyncio
    async def test_dispatcher_routes_openclaw(self):
        """Dispatch with type=openclaw calls OpenClawNotifier."""
        config = NotificationsConfig(
            openclaw_channel="telegram",
            openclaw_target="123456",
            desktop_enabled=False,
        )
        dispatcher = NotificationDispatcher(config)

        rule = _make_rule(
            "r1", notif_type="openclaw", channel="telegram", target="123456"
        )
        evaluation = _make_eval()
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="test")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("os.path.exists", return_value=False),
        ):
            await dispatcher.dispatch(alert)

        await dispatcher.close()

    @pytest.mark.asyncio
    async def test_dispatcher_openclaw_with_desktop_bonus(self):
        """openclaw type also triggers desktop notification."""
        config = NotificationsConfig(
            openclaw_channel="telegram",
            openclaw_target="123456",
            desktop_enabled=True,
        )
        dispatcher = NotificationDispatcher(config)

        rule = _make_rule("r1", notif_type="openclaw")
        evaluation = _make_eval()
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="test")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("os.path.exists", return_value=False),
            patch.object(
                dispatcher._desktop, "notify", return_value=True
            ) as mock_desktop,
        ):
            await dispatcher.dispatch(alert)

        # Desktop notification also called as bonus
        mock_desktop.assert_called_once()

        await dispatcher.close()

    @pytest.mark.asyncio
    async def test_dispatcher_multichannel_fanout(self):
        """Comma-separated channels/targets fan out to multiple notifiers."""
        config = NotificationsConfig(
            openclaw_channel="slack",
            openclaw_target="C123",
            desktop_enabled=False,
        )
        dispatcher = NotificationDispatcher(config)

        rule = _make_rule(
            "r1",
            notif_type="openclaw",
            channel="slack,discord",
            target="C123,987654321",
        )
        evaluation = _make_eval()
        alert = AlertEvent(rule=rule, evaluation=evaluation, scene_summary="test")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_proc
            ) as mock_exec,
            patch("os.path.exists", return_value=False),
        ):
            await dispatcher.dispatch(alert)

        # Should have been called twice — once for slack, once for discord
        assert mock_exec.call_count == 2
        calls = mock_exec.call_args_list
        # First call: slack
        args0 = calls[0][0]
        idx = args0.index("--channel")
        assert args0[idx + 1] == "slack"
        idx = args0.index("--target")
        assert args0[idx + 1] == "C123"
        # Second call: discord
        args1 = calls[1][0]
        idx = args1.index("--channel")
        assert args1[idx + 1] == "discord"
        idx = args1.index("--target")
        assert args1[idx + 1] == "987654321"

        await dispatcher.close()


class TestMultiUserOwnership:
    """Multi-user rule isolation — each person owns their rules."""

    def test_owner_fields_default_empty(self):
        """WatchRule owner_id and owner_name default to empty string."""
        rule = _make_rule("r1")
        assert rule.owner_id == ""
        assert rule.owner_name == ""

    def test_owner_fields_set(self):
        """WatchRule accepts owner_id and owner_name."""
        rule = WatchRule(
            id="r_owned",
            name="Alice's door watch",
            condition="person at door",
            priority=RulePriority.HIGH,
            notification=NotificationTarget(
                type="openclaw", channel="slack", target="U12345"
            ),
            owner_id="slack:U12345",
            owner_name="Alice",
        )
        assert rule.owner_id == "slack:U12345"
        assert rule.owner_name == "Alice"

    def test_owner_fields_persist_roundtrip(self):
        """owner_id/owner_name survive save -> load via RulesStore."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        store = RulesStore(path)
        rule = WatchRule(
            id="r_persist",
            name="Bob's kitchen watch",
            condition="smoke visible",
            priority=RulePriority.CRITICAL,
            notification=NotificationTarget(
                type="openclaw", channel="discord", target="987654"
            ),
            owner_id="discord:987654",
            owner_name="Bob",
        )
        store.save([rule])

        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].owner_id == "discord:987654"
        assert loaded[0].owner_name == "Bob"

    def test_multiple_owners_coexist(self):
        """Rules from different users coexist in engine."""
        engine = RulesEngine()
        alice_rule = WatchRule(
            id="r_alice",
            name="Alice's rule",
            condition="cat on couch",
            owner_id="slack:U111",
            owner_name="Alice",
        )
        bob_rule = WatchRule(
            id="r_bob",
            name="Bob's rule",
            condition="dog in yard",
            owner_id="discord:D222",
            owner_name="Bob",
        )
        engine.add_rule(alice_rule)
        engine.add_rule(bob_rule)

        all_rules = engine.list_rules()
        assert len(all_rules) == 2

        # Both rules are active
        active = engine.get_active_rules()
        assert len(active) == 2

    def test_owner_in_model_dump(self):
        """model_dump includes owner_id and owner_name."""
        rule = WatchRule(
            id="r_dump",
            name="Test rule",
            condition="test",
            owner_id="slack:U999",
            owner_name="Charlie",
        )
        data = rule.model_dump(mode="json")
        assert data["owner_id"] == "slack:U999"
        assert data["owner_name"] == "Charlie"

    def test_backward_compat_no_owner(self):
        """Rules without owner fields still work (backward compatible)."""
        engine = RulesEngine()
        old_rule = _make_rule("r_old")
        assert old_rule.owner_id == ""
        engine.add_rule(old_rule)
        scene = SceneState()
        alerts = engine.process_evaluations([_make_eval(rule_id="r_old")], scene)
        assert len(alerts) == 1


class TestCameraConfig:
    """Camera configuration and multi-camera support."""

    def test_config_loads_multiple_cameras(self):
        """Config file with two cameras loads both."""
        from physical_mcp.config import PhysicalMCPConfig, CameraConfig

        config = PhysicalMCPConfig(
            cameras=[
                CameraConfig(id="usb:0", name="Camera 1", device_index=0),
                CameraConfig(id="usb:1", name="Camera 2", device_index=1),
            ]
        )
        assert len(config.cameras) == 2
        assert config.cameras[0].id == "usb:0"
        assert config.cameras[1].id == "usb:1"

    def test_config_camera_enabled_filter(self):
        """Only enabled cameras are active."""
        from physical_mcp.config import PhysicalMCPConfig, CameraConfig

        config = PhysicalMCPConfig(
            cameras=[
                CameraConfig(id="usb:0", enabled=True),
                CameraConfig(id="usb:1", enabled=False),
                CameraConfig(id="usb:2", enabled=True),
            ]
        )
        enabled = [c for c in config.cameras if c.enabled]
        assert len(enabled) == 2
        assert {c.id for c in enabled} == {"usb:0", "usb:2"}

    def test_save_config_roundtrip(self):
        """save_config -> load_config preserves camera list."""
        from physical_mcp.config import (
            PhysicalMCPConfig,
            CameraConfig,
            save_config,
            load_config,
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name

        config = PhysicalMCPConfig(
            cameras=[
                CameraConfig(id="usb:0", name="Front", device_index=0),
                CameraConfig(
                    id="http:192.168.1.50",
                    name="iPhone Kitchen",
                    type="http",
                    url="http://192.168.1.50:81/stream",
                ),
            ]
        )
        save_config(config, path)
        loaded = load_config(path)
        assert len(loaded.cameras) == 2
        assert loaded.cameras[1].name == "iPhone Kitchen"
        assert loaded.cameras[1].type == "http"


class TestStaleCache:
    """Server was down, comes back -> fresh state."""

    def test_scene_state_starts_empty(self):
        """New SceneState has empty summary."""
        scene = SceneState()
        assert scene.summary == ""
        assert scene.people_count == 0
        assert scene.update_count == 0

    def test_scene_update_populates_state(self):
        """After update, scene has data."""
        scene = SceneState()
        scene.update(
            summary="Person at desk with laptop",
            objects=["person", "desk", "laptop"],
            people_count=1,
            change_desc="Initial frame",
        )
        assert scene.summary == "Person at desk with laptop"
        assert scene.people_count == 1
        assert scene.update_count == 1
        assert scene.last_updated is not None
