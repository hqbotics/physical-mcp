"""Tests for the Telegram bot (command parsing and state management)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from physical_mcp.bot.telegram_bot import TelegramBot
from physical_mcp.perception.scene_state import SceneState


def _make_bot_state(
    with_scene: bool = True,
    with_rules_engine: bool = True,
) -> dict:
    """Create a mock state dict for bot testing."""
    state: dict = {
        "cameras": {},
        "camera_configs": {},
        "frame_buffers": {},
        "scene_states": {},
        "camera_health": {},
        "_pending_claims": {},
        "_completed_claims": {},
    }

    if with_scene:
        scene = SceneState()
        scene.update(
            summary="Two people sitting at a desk with laptops",
            objects=["laptop", "coffee cup", "monitor"],
            people_count=2,
            change_desc="Person sat down",
        )
        state["scene_states"]["cloud:test"] = scene

        mock_buffer = AsyncMock()
        mock_frame = MagicMock()
        mock_frame.to_jpeg_bytes.return_value = b"\xff\xd8\xff\xe0fake"
        mock_buffer.latest.return_value = mock_frame
        state["frame_buffers"]["cloud:test"] = mock_buffer

        mock_cam = MagicMock()
        mock_cam.is_open.return_value = True
        state["cameras"]["cloud:test"] = mock_cam

    if with_rules_engine:
        from physical_mcp.rules.engine import RulesEngine

        state["rules_engine"] = RulesEngine()
        state["rules_store"] = MagicMock()

    return state


class TestTelegramBotInit:
    def test_construction(self):
        """Bot can be constructed with token and state."""
        state = _make_bot_state(with_scene=False, with_rules_engine=False)
        bot = TelegramBot(
            token="test:token", state=state, base_url="http://localhost:8090"
        )
        assert bot._token == "test:token"
        assert bot._running is False

    def test_base_url_trailing_slash(self):
        """Base URL trailing slash is stripped."""
        state = _make_bot_state(with_scene=False, with_rules_engine=False)
        bot = TelegramBot(token="t", state=state, base_url="http://localhost:8090/")
        assert bot._base_url == "http://localhost:8090"


class TestClaimCodeGeneration:
    @pytest.mark.asyncio
    async def test_setup_generates_claim_code(self):
        """The /setup command generates a 6-character alphanumeric code."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {
            "chat": {"id": 12345},
            "from": {"first_name": "Alice"},
        }
        await bot._cmd_setup(12345, msg)

        # Should have stored a claim code
        assert len(state["_pending_claims"]) == 1
        code = list(state["_pending_claims"].keys())[0]
        assert len(code) == 6
        assert code.isalnum()

        # Should have sent a message with the code
        bot._send.assert_called_once()
        sent_text = bot._send.call_args[0][1]
        assert code in sent_text

    @pytest.mark.asyncio
    async def test_setup_stores_chat_id(self):
        """Claim code stores the user's chat_id for notification."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {
            "chat": {"id": 99999},
            "from": {"first_name": "Bob"},
        }
        await bot._cmd_setup(99999, msg)

        code = list(state["_pending_claims"].keys())[0]
        claim = state["_pending_claims"][code]
        assert claim["chat_id"] == "99999"
        assert claim["user_name"] == "Bob"


class TestCommandRouting:
    @pytest.mark.asyncio
    async def test_start_command(self):
        """The /start command sends a welcome message."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {
            "chat": {"id": 123},
            "from": {"first_name": "Alice"},
            "text": "/start",
        }
        await bot._handle_message(msg)
        bot._send.assert_called_once()
        text = bot._send.call_args[0][1]
        assert "Alice" in text

    @pytest.mark.asyncio
    async def test_help_command(self):
        """The /help command lists available commands."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/help"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "/snap" in text
        assert "/watch" in text
        assert "/rules" in text

    @pytest.mark.asyncio
    async def test_scene_command(self):
        """The /scene command returns camera scene descriptions."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/scene"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "cloud:test" in text
        assert "laptop" in text.lower() or "desk" in text.lower()

    @pytest.mark.asyncio
    async def test_scene_no_cameras(self):
        """The /scene command with no cameras gives helpful message."""
        state = _make_bot_state(with_scene=False)
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/scene"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "No cameras" in text or "setup" in text.lower()


class TestWatchRules:
    @pytest.mark.asyncio
    async def test_watch_creates_rule(self):
        """The /watch command creates a rule in the engine."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {
            "chat": {"id": 123},
            "from": {"first_name": "Alice"},
            "text": "/watch someone at the front door",
        }
        await bot._handle_message(msg)

        # Rule should be created
        engine = state["rules_engine"]
        rules = engine.list_rules()
        assert len(rules) == 1
        assert "front door" in rules[0].condition
        assert rules[0].owner_id == "telegram:123"

        # Confirmation message sent
        text = bot._send.call_args[0][1]
        assert "front door" in text

    @pytest.mark.asyncio
    async def test_watch_no_condition(self):
        """The /watch command without text shows examples."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/watch"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "Examples" in text or "watch for" in text.lower()

    @pytest.mark.asyncio
    async def test_rules_lists_user_rules(self):
        """The /rules command lists rules belonging to the user."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        # Create a rule first
        msg = {
            "chat": {"id": 123},
            "from": {"first_name": "Alice"},
            "text": "/watch packages at the door",
        }
        await bot._handle_message(msg)
        bot._send.reset_mock()

        # List rules
        msg = {"chat": {"id": 123}, "from": {}, "text": "/rules"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "packages" in text.lower()

    @pytest.mark.asyncio
    async def test_rules_empty_state(self):
        """The /rules command with no rules shows helpful message."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/rules"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "No active" in text or "/watch" in text

    @pytest.mark.asyncio
    async def test_stop_deletes_rule(self):
        """The /stop command deletes a rule by ID."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        # Create a rule
        msg = {
            "chat": {"id": 123},
            "from": {"first_name": "Alice"},
            "text": "/watch someone in the yard",
        }
        await bot._handle_message(msg)

        # Get rule ID
        engine = state["rules_engine"]
        rules = engine.list_rules()
        rule_id = rules[0].id
        bot._send.reset_mock()

        # Delete it
        msg = {"chat": {"id": 123}, "from": {}, "text": f"/stop {rule_id}"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "deleted" in text.lower() or "🗑" in text

        # Verify deleted
        assert len(engine.list_rules()) == 0

    @pytest.mark.asyncio
    async def test_stop_wrong_owner(self):
        """A user can't delete another user's rule."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        # User 123 creates a rule
        msg = {
            "chat": {"id": 123},
            "from": {"first_name": "Alice"},
            "text": "/watch cat on the counter",
        }
        await bot._handle_message(msg)

        rule_id = state["rules_engine"].list_rules()[0].id
        bot._send.reset_mock()

        # User 456 tries to delete it
        msg = {"chat": {"id": 456}, "from": {}, "text": f"/stop {rule_id}"}
        await bot._handle_message(msg)
        text = bot._send.call_args[0][1]
        assert "your own" in text.lower() or "can only" in text.lower()

        # Rule should still exist
        assert len(state["rules_engine"].list_rules()) == 1


class TestSnapCommand:
    @pytest.mark.asyncio
    async def test_snap_sends_photo(self):
        """The /snap command sends a camera frame as a photo."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()
        bot._send_photo = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/snap"}
        await bot._handle_message(msg)

        bot._send_photo.assert_called_once()
        call_args = bot._send_photo.call_args
        assert call_args[0][0] == 123  # chat_id
        assert call_args[0][1] == b"\xff\xd8\xff\xe0fake"  # jpeg bytes

    @pytest.mark.asyncio
    async def test_snap_no_cameras(self):
        """The /snap command with no cameras gives helpful message."""
        state = _make_bot_state(with_scene=False)
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()
        bot._send_photo = AsyncMock()

        msg = {"chat": {"id": 123}, "from": {}, "text": "/snap"}
        await bot._handle_message(msg)

        # Should send text, not photo
        bot._send.assert_called_once()
        bot._send_photo.assert_not_called()
        text = bot._send.call_args[0][1]
        assert "No cameras" in text or "setup" in text.lower()


class TestAlertDispatch:
    @pytest.mark.asyncio
    async def test_send_alert_text(self):
        """send_alert sends a text notification."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send = AsyncMock()

        await bot.send_alert(
            chat_id="12345",
            rule_name="Door Watch",
            reason="Person detected at front door",
        )

        bot._send.assert_called_once()
        text = bot._send.call_args[0][1]
        assert "Door Watch" in text
        assert "front door" in text

    @pytest.mark.asyncio
    async def test_send_alert_with_photo(self):
        """send_alert with frame data sends a photo."""
        state = _make_bot_state()
        bot = TelegramBot(token="test:token", state=state)
        bot._send_photo = AsyncMock()

        await bot.send_alert(
            chat_id="12345",
            rule_name="Package Alert",
            reason="Package detected",
            frame_jpeg=b"\xff\xd8fake",
        )

        bot._send_photo.assert_called_once()
