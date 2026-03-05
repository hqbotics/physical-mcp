"""Bidirectional Telegram bot for Physical MCP cloud mode.

Uses the Telegram Bot API via getUpdates long-polling (not webhooks).
This avoids needing a public HTTPS URL for the bot — works behind NAT.

Commands:
    /start        → Welcome message + setup instructions
    /setup        → Generate 6-digit claim code for camera pairing
    /snap         → Take a snapshot and send the current frame
    /scene        → Get the current scene description
    /watch <X>    → Create a watch rule: "alert me when X"
    /rules        → List active watch rules
    /stop <id>    → Delete a watch rule
    /help         → Show available commands
    (free text)   → Ask a question about the scene
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
import time
from typing import Any

import aiohttp

logger = logging.getLogger("physical-mcp")

# Telegram Bot API base URL
_TG_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    """Bidirectional Telegram bot using getUpdates long-polling.

    Args:
        token: Telegram Bot API token from @BotFather
        state: Shared state dict from the MCP server
        base_url: Base URL for the Vision API (for building push URLs)
    """

    def __init__(self, token: str, state: dict[str, Any], base_url: str = ""):
        self._token = token
        self._state = state
        self._base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._offset = 0  # getUpdates offset for pagination
        self._poll_timeout = 30  # Long-poll timeout in seconds

    async def start(self) -> None:
        """Start the bot polling loop."""
        self._session = aiohttp.ClientSession()
        self._running = True

        # Verify token + get bot info
        try:
            me = await self._api("getMe")
            bot_name = me.get("username", "unknown")
            logger.info(f"Telegram bot started: @{bot_name}")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")
            await self.stop()
            return

        # Initialize pending claims dict in state
        self._state.setdefault("_pending_claims", {})
        self._state.setdefault("_completed_claims", {})

        # Start polling loop
        asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the bot."""
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("Telegram bot stopped")

    # ── Telegram API helpers ─────────────────────────────

    async def _api(self, method: str, **kwargs: Any) -> dict:
        """Call Telegram Bot API."""
        if not self._session:
            raise RuntimeError("Bot session not initialized")
        url = _TG_API.format(token=self._token, method=method)
        async with self._session.post(url, json=kwargs) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram API error: {data.get('description', 'unknown')}"
                )
            return data.get("result", {})

    async def _send(self, chat_id: int | str, text: str, **kwargs: Any) -> dict:
        """Send a text message."""
        return await self._api(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            **kwargs,
        )

    async def _send_photo(
        self,
        chat_id: int | str,
        photo_bytes: bytes,
        caption: str = "",
    ) -> dict:
        """Send a photo with optional caption."""
        if not self._session:
            raise RuntimeError("Bot session not initialized")
        url = _TG_API.format(token=self._token, method="sendPhoto")
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field(
            "photo", photo_bytes, filename="frame.jpg", content_type="image/jpeg"
        )
        if caption:
            data.add_field("caption", caption)
        async with self._session.post(url, data=data) as resp:
            result = await resp.json()
            if not result.get("ok"):
                raise RuntimeError(f"sendPhoto failed: {result.get('description')}")
            return result.get("result", {})

    # ── Polling loop ──────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Long-poll for updates and dispatch messages."""
        logger.info("Telegram bot polling loop started")
        while self._running:
            try:
                updates = await self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=self._poll_timeout,
                )
                for update in updates:
                    self._offset = update["update_id"] + 1
                    msg = update.get("message")
                    if msg:
                        asyncio.create_task(self._handle_message(msg))
                    cb = update.get("callback_query")
                    if cb:
                        asyncio.create_task(self._handle_callback_query(cb))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram poll error: {e}")
                await asyncio.sleep(5)  # Back off on errors

    # ── Callback query handler (feedback buttons) ─────────

    async def _handle_callback_query(self, cb: dict) -> None:
        """Handle inline keyboard button presses (👍/👎/😤 feedback)."""
        cb_id = cb.get("id", "")
        data = cb.get("data", "")
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        message_id = cb.get("message", {}).get("message_id")

        if not data.startswith("fb:"):
            await self._api("answerCallbackQuery", callback_query_id=cb_id)
            return

        # Parse fb:{eval_id}:{feedback_type}
        parts = data.split(":")
        if len(parts) != 3:
            await self._api(
                "answerCallbackQuery",
                callback_query_id=cb_id,
                text="Invalid feedback data",
            )
            return

        try:
            eval_id = int(parts[1])
            feedback_type = parts[2]  # correct, wrong, missed
        except (ValueError, IndexError):
            await self._api(
                "answerCallbackQuery",
                callback_query_id=cb_id,
                text="Invalid feedback data",
            )
            return

        if feedback_type not in ("correct", "wrong", "missed"):
            await self._api(
                "answerCallbackQuery",
                callback_query_id=cb_id,
                text="Unknown feedback type",
            )
            return

        # Record feedback in EvalLog
        eval_log = self._state.get("eval_log")
        if eval_log:
            try:
                eval_log.record_feedback(
                    eval_id=eval_id,
                    feedback=feedback_type,
                    telegram_message_id=message_id,
                    chat_id=str(chat_id) if chat_id else "",
                )
                emoji = {
                    "correct": "\u2705",
                    "wrong": "\u274c",
                    "missed": "\U0001f50d",
                }.get(feedback_type, "\u2705")
                await self._api(
                    "answerCallbackQuery",
                    callback_query_id=cb_id,
                    text=f"{emoji} Feedback recorded — thank you!",
                )
            except Exception as e:
                logger.warning(f"Failed to record feedback: {e}")
                await self._api(
                    "answerCallbackQuery",
                    callback_query_id=cb_id,
                    text="Failed to record feedback",
                )
        else:
            await self._api(
                "answerCallbackQuery",
                callback_query_id=cb_id,
                text="\u2705 Feedback noted (eval log not available)",
            )

        # Remove inline keyboard from the message
        if chat_id and message_id:
            try:
                await self._api(
                    "editMessageReplyMarkup",
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup={"inline_keyboard": []},
                )
            except Exception:
                pass  # Best-effort — message might be too old

    # ── Message handler ───────────────────────────────────

    async def _handle_message(self, msg: dict) -> None:
        """Route incoming message to the appropriate handler."""
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()

        if not text:
            return

        # Command routing
        cmd = text.split()[0].lower().split("@")[0]  # Remove @botname suffix

        try:
            if cmd == "/start":
                await self._cmd_start(chat_id, msg)
            elif cmd == "/help":
                await self._cmd_help(chat_id)
            elif cmd == "/setup":
                await self._cmd_setup(chat_id, msg)
            elif cmd == "/snap" or cmd == "/snapshot":
                await self._cmd_snap(chat_id)
            elif cmd == "/scene":
                await self._cmd_scene(chat_id)
            elif cmd in ("/watch", "/alert"):
                await self._cmd_watch(chat_id, text, msg)
            elif cmd == "/rules" or cmd == "/myrules":
                await self._cmd_rules(chat_id)
            elif cmd in ("/stop", "/delete", "/remove"):
                await self._cmd_stop(chat_id, text)
            elif cmd == "/accuracy":
                await self._cmd_accuracy(chat_id)
            elif cmd == "/analyze":
                await self._cmd_analyze(chat_id)
            elif cmd.startswith("/"):
                await self._send(
                    chat_id, "Unknown command. Send /help for available commands."
                )
            else:
                # Detect watch-rule intent from natural language
                lower = text.lower()
                if self._is_watch_intent(lower):
                    # Extract the condition from natural language
                    condition = self._extract_watch_condition(text)
                    await self._cmd_watch(chat_id, f"/watch {condition}", msg)
                else:
                    # Free text — ask about the scene
                    await self._cmd_ask(chat_id, text)
        except Exception as e:
            logger.error(f"Error handling message from {chat_id}: {e}")
            await self._send(chat_id, f"Sorry, something went wrong: {e}")

    # ── Natural language intent detection ───────────────────

    _WATCH_PREFIXES = (
        "tell me when",
        "tell me if",
        "let me know when",
        "let me know if",
        "alert me when",
        "alert me if",
        "notify me when",
        "notify me if",
        "watch for",
        "watch when",
        "warn me when",
        "warn me if",
        "ping me when",
        "ping me if",
        "message me when",
        "message me if",
    )

    def _is_watch_intent(self, text_lower: str) -> bool:
        """Check if free text looks like a watch-rule request."""
        return any(text_lower.startswith(p) for p in self._WATCH_PREFIXES)

    def _extract_watch_condition(self, text: str) -> str:
        """Extract the watch condition from natural language.

        'tell me when someone drinks water' → 'someone drinks water'
        """
        lower = text.lower()
        for prefix in self._WATCH_PREFIXES:
            if lower.startswith(prefix):
                condition = text[len(prefix) :].strip()
                # Remove leading articles/filler
                for filler in ("there is ", "there's ", "i ", "you see "):
                    if condition.lower().startswith(filler):
                        condition = condition[len(filler) :]
                return condition or text
        return text

    # ── Command handlers ──────────────────────────────────

    async def _cmd_start(self, chat_id: int, msg: dict) -> None:
        """Welcome message."""
        name = msg.get("from", {}).get("first_name", "there")
        await self._send(
            chat_id,
            f"Hey {name}! I'm your Physical MCP camera assistant.\n\n"
            "I can show you what your cameras see, create watch rules, "
            "and alert you when things happen.\n\n"
            "*Quick start:*\n"
            "- /setup — Connect a new camera\n"
            "- /snap — See what the camera sees right now\n"
            "- /watch someone at the door — Get alerts\n"
            "- /rules — See your active watch rules\n\n"
            "Or just ask me anything, like:\n"
            '_"What do you see?"_\n'
            '_"Is anyone in the kitchen?"_',
        )

    async def _cmd_help(self, chat_id: int) -> None:
        """Show available commands."""
        await self._send(
            chat_id,
            "*Available Commands:*\n\n"
            "/setup — Connect a new camera\n"
            "/snap — Take a snapshot\n"
            "/scene — Describe current scene\n"
            "/watch <condition> — Create alert rule\n"
            "/rules — List your watch rules\n"
            "/stop <rule\\_id> — Delete a rule\n"
            "/accuracy — Show rule accuracy stats\n"
            "/analyze — Run self-analysis to tune rules\n"
            "/help — Show this message\n\n"
            "Or just type a question about what the camera sees!",
        )

    async def _cmd_setup(self, chat_id: int, msg: dict) -> None:
        """Generate claim code for camera pairing."""
        # Generate 6-character alphanumeric code
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

        # Store in pending claims
        pending = self._state.setdefault("_pending_claims", {})
        user = msg.get("from", {})
        pending[code] = {
            "chat_id": str(chat_id),
            "user_name": user.get("first_name", ""),
            "camera_name": f"Camera-{code[:4]}",
            "created_at": time.time(),
        }

        await self._send(
            chat_id,
            f"*Your setup code:* `{code}`\n\n"
            "To connect your camera:\n"
            "1. Power on the camera unit\n"
            "2. Connect your phone to the *PhysicalMCP-XXXX* WiFi\n"
            "3. Open the setup page in your browser\n"
            "4. Enter the code above when prompted\n\n"
            f"This code expires in 15 minutes.",
        )

        # Auto-expire claim after 15 minutes
        async def _expire_claim():
            await asyncio.sleep(15 * 60)
            pending.pop(code, None)

        asyncio.create_task(_expire_claim())

    async def _cmd_snap(self, chat_id: int) -> None:
        """Send a snapshot from the camera."""
        # Find a camera with frames
        buffers = self._state.get("frame_buffers", {})
        cameras = self._state.get("cameras", {})

        frame = None
        cam_id = None
        for cid, buf in buffers.items():
            f = await buf.latest()
            if f is not None:
                frame = f
                cam_id = cid
                break

        # Fallback: try grabbing directly from camera
        if frame is None:
            for cid, cam in cameras.items():
                if cam.is_open():
                    try:
                        frame = await cam.grab_frame()
                        cam_id = cid
                        break
                    except Exception:
                        continue

        if frame is None:
            await self._send(
                chat_id,
                "No cameras connected or no frames available.\n"
                "Use /setup to connect a camera.",
            )
            return

        # Get scene description
        scenes = self._state.get("scene_states", {})
        scene = scenes.get(cam_id)
        caption = ""
        if scene and scene.summary:
            caption = f"📷 *{cam_id}*\n{scene.summary}"
        else:
            caption = f"📷 *{cam_id}*"

        jpeg_bytes = frame.to_jpeg_bytes(quality=80)
        await self._send_photo(chat_id, jpeg_bytes, caption=caption)

    async def _cmd_scene(self, chat_id: int) -> None:
        """Describe the current scene."""
        scenes = self._state.get("scene_states", {})
        if not scenes:
            await self._send(chat_id, "No cameras active. Use /setup to connect one.")
            return

        lines = []
        for cid, scene in scenes.items():
            if scene.summary:
                lines.append(f"📷 *{cid}*: {scene.summary}")
                objects_list = getattr(scene, "objects_present", []) or []
                if objects_list:
                    objects_str = ", ".join(objects_list[:10])
                    lines.append(f"   Objects: {objects_str}")
                people = getattr(scene, "people_count", 0) or 0
                if people > 0:
                    lines.append(f"   People: {people}")
            else:
                lines.append(f"📷 *{cid}*: No analysis yet")

        await self._send(chat_id, "\n".join(lines))

    async def _cmd_watch(self, chat_id: int, text: str, msg: dict) -> None:
        """Create a watch rule from natural language."""
        # Extract condition from text (remove command prefix)
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(
                chat_id,
                "Tell me what to watch for!\n\n"
                "Examples:\n"
                "- /watch someone at the front door\n"
                "- /watch package delivered\n"
                "- /watch my cat on the counter\n"
                "- /watch fire or smoke",
            )
            return

        condition = parts[1].strip()
        user = msg.get("from", {})
        owner_id = f"telegram:{chat_id}"
        owner_name = user.get("first_name", "")

        # Create the rule via the rules engine
        engine = self._state.get("rules_engine")
        if engine is None:
            await self._send(chat_id, "Rules engine not available. Try again later.")
            return

        import uuid
        from ..rules.models import NotificationTarget, RulePriority, WatchRule

        rule = WatchRule(
            id=f"r_{uuid.uuid4().hex[:8]}",
            name=condition[:50],
            condition=condition,
            camera_id="",  # All cameras
            priority=RulePriority.MEDIUM,
            notification=NotificationTarget(
                type="telegram",
                target=str(chat_id),
            ),
            cooldown_seconds=60,
            owner_id=owner_id,
            owner_name=owner_name,
        )
        engine.add_rule(rule)

        # Persist
        store = self._state.get("rules_store")
        if store:
            store.save(engine.list_rules())

        # Start perception loops
        ensure_loops = self._state.get("_ensure_perception_loops")
        if ensure_loops:
            asyncio.ensure_future(ensure_loops())

        await self._send(
            chat_id,
            f"👁 *Watching for:* {condition}\n\n"
            f"Rule ID: `{rule.id}`\n"
            "I'll alert you when this is detected.\n"
            "Use /rules to see all active rules.",
        )

    async def _cmd_rules(self, chat_id: int) -> None:
        """List rules owned by this user."""
        engine = self._state.get("rules_engine")
        if engine is None:
            await self._send(chat_id, "No rules engine available.")
            return

        owner_id = f"telegram:{chat_id}"
        rules = engine.list_rules()
        my_rules = [
            r
            for r in rules
            if getattr(r, "owner_id", "") == owner_id
            or getattr(r, "owner_id", "") == ""
        ]

        if not my_rules:
            await self._send(
                chat_id,
                "No active watch rules.\n\n"
                "Create one with:\n"
                "/watch someone at the front door",
            )
            return

        lines = ["*Your Watch Rules:*\n"]
        for r in my_rules:
            status = "✅" if r.enabled else "⏸"
            owner_tag = " (global)" if not getattr(r, "owner_id", "") else ""
            lines.append(f"{status} `{r.id}` — {r.condition}{owner_tag}")
            if getattr(r, "trigger_count", 0) > 0:
                lines.append(f"   Triggered {r.trigger_count} times")

        lines.append(f"\n_{len(my_rules)} rule(s) total_")
        await self._send(chat_id, "\n".join(lines))

    async def _cmd_stop(self, chat_id: int, text: str) -> None:
        """Delete a watch rule."""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(
                chat_id,
                "Specify the rule ID to delete.\n"
                "Use /rules to see your rules and their IDs.",
            )
            return

        rule_id = parts[1].strip()
        engine = self._state.get("rules_engine")
        if engine is None:
            await self._send(chat_id, "Rules engine not available.")
            return

        # Check ownership
        owner_id = f"telegram:{chat_id}"
        rules = engine.list_rules()
        target = None
        for r in rules:
            if r.id == rule_id:
                target = r
                break

        if target is None:
            await self._send(chat_id, f"Rule `{rule_id}` not found.")
            return

        rule_owner = getattr(target, "owner_id", "")
        if rule_owner and rule_owner != owner_id:
            await self._send(chat_id, "You can only delete your own rules.")
            return

        engine.remove_rule(rule_id)
        store = self._state.get("rules_store")
        if store:
            store.save(engine.list_rules())

        await self._send(
            chat_id,
            f"🗑 Rule `{rule_id}` deleted.\nWas watching for: _{target.condition}_",
        )

    async def _cmd_accuracy(self, chat_id: int) -> None:
        """Show per-rule accuracy stats from the eval log."""
        eval_log = self._state.get("eval_log")
        if not eval_log:
            await self._send(chat_id, "Evaluation log not available.")
            return

        all_stats = eval_log.get_all_rule_stats()
        if not all_stats:
            await self._send(
                chat_id,
                "\U0001f4ca *No accuracy data yet.*\n\n"
                "Stats accumulate as you use \U0001f44d/\U0001f44e buttons on alerts.",
            )
            return

        engine = self._state.get("rules_engine")
        rules_map = {}
        if engine:
            for r in engine.list_rules():
                rules_map[r.id] = r.condition

        lines = ["\U0001f4ca *Rule Accuracy Report*\n"]
        for s in all_stats:
            rid = s["rule_id"]
            condition = rules_map.get(rid, rid)
            tp = s.get("true_positives", 0)
            fp = s.get("false_positives", 0)
            fn = s.get("false_negatives", 0)
            acc = s.get("accuracy")
            threshold = s.get("confidence_threshold", 0.3)
            hint = s.get("prompt_hint", "")

            total_feedback = tp + fp + fn
            acc_str = f"{acc:.0%}" if acc is not None else "N/A"

            lines.append(f"\U0001f441 *{condition[:40]}*")
            lines.append(
                f"  \u2705 {tp} correct | \u274c {fp} wrong | \U0001f50d {fn} missed"
            )
            lines.append(f"  Accuracy: {acc_str} | Threshold: {threshold:.2f}")
            if hint:
                lines.append(f"  Hint: _{hint}_")
            if total_feedback == 0:
                lines.append("  _No feedback yet — use buttons on alerts_")
            lines.append("")

        await self._send(chat_id, "\n".join(lines))

    async def _cmd_analyze(self, chat_id: int) -> None:
        """Run self-analysis on all rules to tune thresholds."""
        analyzer_obj = self._state.get("self_analyzer")
        if not analyzer_obj:
            await self._send(
                chat_id,
                "Self-analyzer not available.\n"
                "Make sure a vision provider is configured.",
            )
            return

        engine = self._state.get("rules_engine")
        if not engine:
            await self._send(chat_id, "Rules engine not available.")
            return

        rule_ids = [r.id for r in engine.list_rules()]
        if not rule_ids:
            await self._send(chat_id, "No rules to analyze.")
            return

        await self._send(chat_id, "\U0001f9e0 Running self-analysis... please wait.")

        try:
            results = await analyzer_obj.analyze_all_rules(rule_ids)
        except Exception as e:
            await self._send(chat_id, f"Self-analysis failed: {e}")
            return

        lines = ["\U0001f9e0 *Self-Analysis Complete*\n"]
        for r in results:
            rid = r.get("rule_id", "?")
            # Find rule name
            rule_name = rid
            for rule in engine.list_rules():
                if rule.id == rid:
                    rule_name = rule.condition[:40]
                    break

            if r.get("skipped"):
                lines.append(f"*{rule_name}:*")
                lines.append(f"  Skipped — {r.get('reason', 'unknown')}")
                lines.append("")
                continue

            if r.get("error"):
                lines.append(f"*{rule_name}:*")
                lines.append(f"  Error — {r['error'][:80]}")
                lines.append("")
                continue

            lines.append(f"*{rule_name}:*")
            tc = r.get("threshold_change", "")
            if tc:
                lines.append(f"  Threshold: {tc}")
            hc = r.get("hint_change", "")
            if hc:
                lines.append(f"  Hint: {hc}")
            reasoning = r.get("reasoning", "")
            if reasoning:
                lines.append(f"  _{reasoning[:120]}_")
            lines.append("")

        await self._send(chat_id, "\n".join(lines))

    async def _cmd_ask(self, chat_id: int, text: str) -> None:
        """Handle free-text questions about the scene."""
        # Get current scene
        scenes = self._state.get("scene_states", {})
        if not scenes:
            await self._send(
                chat_id,
                "No cameras connected. Use /setup to add one.",
            )
            return

        # Find first camera with a scene
        scene = None
        cam_id = None
        for cid, s in scenes.items():
            if s.summary:
                scene = s
                cam_id = cid
                break

        if scene is None:
            await self._send(
                chat_id,
                "No scene analysis available yet. The camera might still be starting up.\n"
                "Try /snap to see the raw frame.",
            )
            return

        # Use the analyzer to answer the question with the scene context
        analyzer = self._state.get("analyzer")
        if analyzer and analyzer.has_provider:
            # Get latest frame for visual analysis
            buffers = self._state.get("frame_buffers", {})
            buf = buffers.get(cam_id)
            frame = await buf.latest() if buf else None

            if frame:
                try:
                    config = self._state.get("config")
                    answer = await analyzer.answer_question(
                        frame, scene, text, config=config
                    )
                    await self._send(chat_id, answer)
                    return
                except Exception as e:
                    logger.warning(f"Analyzer question failed: {e}")

        # Fallback: use scene summary as context
        await self._send(
            chat_id,
            f"📷 *{cam_id}*: {scene.summary}\n\n"
            f"_(I don't have a vision provider to answer questions directly. "
            f"This is the last scene analysis.)_",
        )

    # ── Alert dispatch ────────────────────────────────────

    async def send_alert(
        self,
        chat_id: str,
        rule_name: str,
        reason: str,
        frame_jpeg: bytes | None = None,
    ) -> None:
        """Send an alert notification to a Telegram user.

        Called by the notification dispatcher when a rule triggers.
        """
        text = f"🚨 *Alert: {rule_name}*\n\n{reason}"

        if frame_jpeg:
            await self._send_photo(int(chat_id), frame_jpeg, caption=text)
        else:
            await self._send(int(chat_id), text)
