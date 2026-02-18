"""HQB-12 Benchmark: Multi-Client Concurrency & Thread Safety

Benchmark-driven development for Phase 1 (Single-Daemon v0.2.0).
These tests validate that physical-mcp can safely handle multiple
concurrent clients operating on shared state.

Run: uv run pytest tests/test_benchmark_multiclient.py -v

Categories:
  B1  - RulesEngine concurrent access (asyncio.Lock needed)
  B2  - SceneState concurrent updates (asyncio.Lock needed)
  B3  - MemoryStore concurrent file ops (file locking needed)
  B3T - MemoryStore THREAD-based tests (real multi-process danger)
  B4  - AlertQueue multi-subscriber drain (already locked)
  B5  - Event Bus multi-subscriber routing (new component)
  B6  - End-to-end multi-client simulation
  S   - STRESS TESTS with real-world scenario descriptions
  Perf- Performance speed gates

Each stress test documents:
  - Real-world scenario (what user behavior it simulates)
  - Scale (N clients x M requests)
  - Pass/fail threshold
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from physical_mcp.alert_queue import AlertQueue
from physical_mcp.memory import MemoryStore
from physical_mcp.perception.scene_state import SceneState
from physical_mcp.rules.engine import RulesEngine
from physical_mcp.rules.models import (
    NotificationTarget,
    PendingAlert,
    RuleEvaluation,
    RulePriority,
    WatchRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(rule_id: str = "r_1", cooldown: int = 0) -> WatchRule:
    """Create a test WatchRule with zero cooldown by default."""
    return WatchRule(
        id=rule_id,
        name=f"Rule {rule_id}",
        condition=f"condition for {rule_id}",
        priority=RulePriority.MEDIUM,
        notification=NotificationTarget(type="local"),
        cooldown_seconds=cooldown,
    )


def _make_eval(rule_id: str = "r_1", triggered: bool = True, confidence: float = 0.9) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id, triggered=triggered, confidence=confidence, reasoning="bench"
    )


def _make_alert(alert_id: str = "pa_1", ttl: int = 300) -> PendingAlert:
    return PendingAlert(
        id=alert_id,
        timestamp=datetime.now(),
        change_level="major",
        change_description="bench change",
        frame_base64="dGVzdA==",
        scene_context="bench scene",
        active_rules=[{"id": "r_1", "name": "Rule", "condition": "c", "priority": "medium"}],
        expires_at=datetime.now() + timedelta(seconds=ttl),
    )


# ===========================================================================
# B1 — RulesEngine Concurrent Access
# ===========================================================================

class TestB1_RulesEngine_Concurrency:
    """RulesEngine._rules dict is currently unprotected.
    These tests verify safety under concurrent add/remove/list/evaluate.
    """

    @pytest.mark.asyncio
    async def test_b1_01_concurrent_add_rules(self):
        """50 coroutines adding rules simultaneously — all should persist."""
        engine = RulesEngine()
        N = 50

        async def add(i: int):
            engine.add_rule(_make_rule(f"r_{i}"))

        await asyncio.gather(*(add(i) for i in range(N)))
        assert len(engine.list_rules()) == N

    @pytest.mark.asyncio
    async def test_b1_02_concurrent_add_remove(self):
        """Add 100 rules, then 50 coroutines remove while 50 add new ones."""
        engine = RulesEngine()
        # Pre-populate
        for i in range(100):
            engine.add_rule(_make_rule(f"r_{i}"))

        async def remove(i: int):
            engine.remove_rule(f"r_{i}")

        async def add_new(i: int):
            engine.add_rule(_make_rule(f"r_new_{i}"))

        tasks = [remove(i) for i in range(50)] + [add_new(i) for i in range(50)]
        await asyncio.gather(*tasks)

        # Should have: 50 originals (r_50..r_99) + 50 new (r_new_0..r_new_49) = 100
        rules = engine.list_rules()
        rule_ids = {r.id for r in rules}
        assert len(rules) == 100
        for i in range(50, 100):
            assert f"r_{i}" in rule_ids
        for i in range(50):
            assert f"r_new_{i}" in rule_ids

    @pytest.mark.asyncio
    async def test_b1_03_concurrent_list_during_mutation(self):
        """list_rules() while add/remove is happening — should not crash."""
        engine = RulesEngine()
        errors = []

        async def mutate():
            for i in range(100):
                engine.add_rule(_make_rule(f"r_mut_{i}"))
                await asyncio.sleep(0)
                engine.remove_rule(f"r_mut_{i}")

        async def read():
            for _ in range(200):
                try:
                    rules = engine.list_rules()
                    _ = len(rules)  # Force iteration
                except RuntimeError as e:
                    errors.append(str(e))
                await asyncio.sleep(0)

        await asyncio.gather(mutate(), read(), read())
        # With proper locking, no RuntimeError (dict changed during iteration)
        assert len(errors) == 0, f"Got {len(errors)} RuntimeErrors: {errors[:3]}"

    @pytest.mark.asyncio
    async def test_b1_04_concurrent_evaluate_same_rule(self):
        """Multiple evaluations against same rule concurrently.
        With cooldown=0, each should trigger. Verifies no lost updates.
        """
        engine = RulesEngine()
        engine.add_rule(_make_rule("r_1", cooldown=0))
        scene = SceneState(summary="test")
        N = 20
        all_alerts = []

        async def evaluate(i: int):
            alerts = engine.process_evaluations(
                [_make_eval("r_1")], scene
            )
            all_alerts.extend(alerts)

        await asyncio.gather(*(evaluate(i) for i in range(N)))
        # With cooldown=0 and proper locking, first eval triggers,
        # subsequent ones may or may not depending on timing.
        # At minimum: at least 1 alert should fire.
        assert len(all_alerts) >= 1

    @pytest.mark.asyncio
    async def test_b1_05_concurrent_get_active_rules(self):
        """get_active_rules() during mutations — no crash, consistent snapshot."""
        engine = RulesEngine()
        for i in range(20):
            engine.add_rule(_make_rule(f"r_{i}"))
        errors = []

        async def toggle():
            for i in range(20):
                rule = engine._rules.get(f"r_{i}")
                if rule:
                    rule.enabled = not rule.enabled
                await asyncio.sleep(0)

        async def read_active():
            for _ in range(50):
                try:
                    active = engine.get_active_rules()
                    # Should always be a valid list
                    assert isinstance(active, list)
                except RuntimeError as e:
                    errors.append(str(e))
                await asyncio.sleep(0)

        await asyncio.gather(toggle(), read_active(), read_active())
        assert len(errors) == 0, f"Got {len(errors)} errors: {errors[:3]}"


# ===========================================================================
# B2 — SceneState Concurrent Updates
# ===========================================================================

class TestB2_SceneState_Concurrency:
    """SceneState fields are currently unprotected.
    These tests verify update() and record_change() are safe under concurrency.
    """

    @pytest.mark.asyncio
    async def test_b2_01_concurrent_updates(self):
        """50 coroutines calling update() simultaneously."""
        state = SceneState()
        N = 50

        async def updater(i: int):
            state.update(
                summary=f"Scene {i}",
                objects=[f"obj_{i}"],
                people_count=i,
                change_desc=f"change {i}",
            )

        await asyncio.gather(*(updater(i) for i in range(N)))
        # update_count must equal N — no lost increments
        assert state.update_count == N

    @pytest.mark.asyncio
    async def test_b2_02_concurrent_record_change(self):
        """100 coroutines recording changes — all must appear in log."""
        state = SceneState()
        N = 100

        async def record(i: int):
            state.record_change(f"change_{i}")

        await asyncio.gather(*(record(i) for i in range(N)))
        log = state.get_change_log(minutes=60)
        assert len(log) == N

    @pytest.mark.asyncio
    async def test_b2_03_read_during_write(self):
        """to_dict() and get_change_log() while update() is happening — no crash."""
        state = SceneState()
        errors = []

        async def writer():
            for i in range(100):
                state.update(f"scene_{i}", [f"o_{i}"], i % 5, f"chg_{i}")
                await asyncio.sleep(0)

        async def reader():
            for _ in range(200):
                try:
                    d = state.to_dict()
                    assert "summary" in d
                    log = state.get_change_log(minutes=60)
                    assert isinstance(log, list)
                except Exception as e:
                    errors.append(str(e))
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader(), reader())
        assert len(errors) == 0, f"Errors: {errors[:3]}"

    @pytest.mark.asyncio
    async def test_b2_04_update_count_atomicity(self):
        """update_count should be exactly N after N concurrent updates."""
        state = SceneState()
        N = 200

        async def bump(i: int):
            state.update(f"s{i}", [], 0, f"c{i}")

        await asyncio.gather(*(bump(i) for i in range(N)))
        # If update_count += 1 is not atomic, we'll lose increments
        assert state.update_count == N, f"Expected {N}, got {state.update_count}"


# ===========================================================================
# B3 — MemoryStore Concurrent File Operations
# ===========================================================================

class TestB3_MemoryStore_Concurrency:
    """MemoryStore._parse() + _write() is a read-modify-write cycle
    with NO file locking. Concurrent writes will clobber each other.
    """

    @pytest.fixture
    def tmp_memory(self, tmp_path):
        """Create a MemoryStore pointing at a temp file."""
        path = tmp_path / "memory.md"
        return MemoryStore(str(path))

    @pytest.mark.asyncio
    async def test_b3_01_concurrent_append_events(self, tmp_memory):
        """20 coroutines appending events — none should be lost."""
        N = 20

        async def append(i: int):
            tmp_memory.append_event(f"event_{i}")

        await asyncio.gather(*(append(i) for i in range(N)))
        events = tmp_memory.get_recent_events(count=100)
        assert len(events) == N, (
            f"Expected {N} events, got {len(events)}. "
            f"Lost {N - len(events)} events due to race conditions."
        )

    @pytest.mark.asyncio
    async def test_b3_02_concurrent_set_preferences(self, tmp_memory):
        """20 coroutines setting different preferences — all should persist."""
        N = 20

        async def set_pref(i: int):
            tmp_memory.set_preference(f"key_{i}", f"value_{i}")

        await asyncio.gather(*(set_pref(i) for i in range(N)))
        content = tmp_memory.read_all()
        for i in range(N):
            assert f"key_{i}" in content, f"Preference key_{i} lost!"

    @pytest.mark.asyncio
    async def test_b3_03_concurrent_rule_context(self, tmp_memory):
        """Concurrent set + remove of rule contexts."""
        async def set_ctx(i: int):
            tmp_memory.set_rule_context(f"rule_{i}", f"context for {i}")

        async def remove_ctx(i: int):
            tmp_memory.remove_rule_context(f"rule_{i}")

        # Set 20 contexts
        await asyncio.gather(*(set_ctx(i) for i in range(20)))

        # Remove first 10 while setting 10 more
        tasks = [remove_ctx(i) for i in range(10)] + [set_ctx(i + 20) for i in range(10)]
        await asyncio.gather(*tasks)

        content = tmp_memory.read_all()
        # Rules 0-9 should be removed, 10-19 and 20-29 should exist
        for i in range(10, 30):
            assert f"rule_{i}" in content, f"rule_{i} missing!"
        for i in range(10):
            assert f"rule_{i} |" not in content, f"rule_{i} should have been removed!"

    @pytest.mark.asyncio
    async def test_b3_04_concurrent_read_write(self, tmp_memory):
        """read_all() while writes are happening — should not crash or return corrupt data."""
        errors = []

        async def writer():
            for i in range(30):
                tmp_memory.append_event(f"write_{i}")
                await asyncio.sleep(0)

        async def reader():
            for _ in range(50):
                try:
                    content = tmp_memory.read_all()
                    # Should always be valid markdown (starts with # or empty)
                    if content:
                        assert content.startswith("# "), f"Corrupt header: {content[:50]}"
                except Exception as e:
                    errors.append(str(e))
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader(), reader())
        assert len(errors) == 0, f"Errors: {errors[:3]}"


# ===========================================================================
# B3T — MemoryStore THREAD-based Tests (real race conditions)
# ===========================================================================

class TestB3T_MemoryStore_ThreadSafety:
    """MemoryStore file operations from multiple THREADS.

    When physical-mcp serves HTTP clients, aiohttp may dispatch handlers
    across threads (or the MemoryStore could be called from sync contexts
    in thread pool executors). These tests use real threads to expose
    the read-modify-write race in _parse() + _write().
    """

    @pytest.fixture
    def tmp_memory_path(self, tmp_path):
        return str(tmp_path / "memory.md")

    def test_b3t_01_threaded_append_events(self, tmp_memory_path):
        """10 threads each appending 10 events — all 100 should persist.
        This WILL fail without file locking because threads truly preempt.
        """
        N_THREADS = 10
        N_EVENTS = 10
        total_expected = N_THREADS * N_EVENTS
        barrier = threading.Barrier(N_THREADS)

        def worker(thread_id: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()  # All threads start simultaneously
            for i in range(N_EVENTS):
                mem.append_event(f"thread_{thread_id}_event_{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        mem = MemoryStore(tmp_memory_path)
        events = mem.get_recent_events(count=200)
        assert len(events) == total_expected, (
            f"Expected {total_expected} events, got {len(events)}. "
            f"Lost {total_expected - len(events)} events due to thread race conditions. "
            f"This proves MemoryStore needs file locking!"
        )

    def test_b3t_02_threaded_set_preferences(self, tmp_memory_path):
        """10 threads each setting a unique preference — all 10 should persist."""
        N_THREADS = 10
        barrier = threading.Barrier(N_THREADS)

        def worker(thread_id: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            mem.set_preference(f"pref_{thread_id}", f"value_{thread_id}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        mem = MemoryStore(tmp_memory_path)
        content = mem.read_all()
        for t in range(N_THREADS):
            assert f"pref_{t}" in content, (
                f"Preference pref_{t} lost! Thread race overwrote it. "
                f"MemoryStore needs file locking."
            )

    def test_b3t_03_threaded_mixed_operations(self, tmp_memory_path):
        """Mixed thread ops: append events + set rules + set prefs simultaneously."""
        N_THREADS = 6
        barrier = threading.Barrier(N_THREADS)
        errors = []

        def event_writer(thread_id: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            try:
                for i in range(10):
                    mem.append_event(f"t{thread_id}_evt_{i}")
            except Exception as e:
                errors.append(f"Event writer {thread_id}: {e}")

        def rule_writer(thread_id: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            try:
                for i in range(5):
                    mem.set_rule_context(f"rule_t{thread_id}_{i}", f"context_{i}")
            except Exception as e:
                errors.append(f"Rule writer {thread_id}: {e}")

        def pref_writer(thread_id: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            try:
                for i in range(5):
                    mem.set_preference(f"key_t{thread_id}_{i}", f"val_{i}")
            except Exception as e:
                errors.append(f"Pref writer {thread_id}: {e}")

        threads = [
            threading.Thread(target=event_writer, args=(0,)),
            threading.Thread(target=event_writer, args=(1,)),
            threading.Thread(target=rule_writer, args=(2,)),
            threading.Thread(target=rule_writer, args=(3,)),
            threading.Thread(target=pref_writer, args=(4,)),
            threading.Thread(target=pref_writer, args=(5,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Thread errors: {errors}"

        mem = MemoryStore(tmp_memory_path)
        content = mem.read_all()
        events = mem.get_recent_events(count=200)

        # 2 threads * 10 events = 20 events expected
        assert len(events) == 20, (
            f"Expected 20 events, got {len(events)}. Race condition!"
        )
        # 2 threads * 5 rules = 10 rule contexts
        for t in [2, 3]:
            for i in range(5):
                assert f"rule_t{t}_{i}" in content, f"Rule context rule_t{t}_{i} missing!"
        # 2 threads * 5 prefs = 10 preferences
        for t in [4, 5]:
            for i in range(5):
                assert f"key_t{t}_{i}" in content, f"Preference key_t{t}_{i} missing!"

    def test_b3t_04_threaded_concurrent_read_write(self, tmp_memory_path):
        """Readers and writers simultaneously — readers should never see corrupt data."""
        mem_writer = MemoryStore(tmp_memory_path)
        # Seed with some data
        for i in range(5):
            mem_writer.append_event(f"seed_{i}")

        N_WRITERS = 3
        N_READERS = 5
        barrier = threading.Barrier(N_WRITERS + N_READERS)
        corrupt_reads = []

        def writer(wid: int):
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            for i in range(20):
                mem.append_event(f"w{wid}_{i}")

        def reader():
            mem = MemoryStore(tmp_memory_path)
            barrier.wait()
            for _ in range(50):
                content = mem.read_all()
                if content and not content.startswith("# Physical MCP Memory"):
                    corrupt_reads.append(content[:100])

        threads = (
            [threading.Thread(target=writer, args=(w,)) for w in range(N_WRITERS)]
            + [threading.Thread(target=reader) for _ in range(N_READERS)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(corrupt_reads) == 0, (
            f"Got {len(corrupt_reads)} corrupt reads! "
            f"First corrupt: {corrupt_reads[0] if corrupt_reads else 'N/A'}"
        )


# ===========================================================================
# B4 — AlertQueue Multi-Subscriber (already has asyncio.Lock)
# ===========================================================================

class TestB4_AlertQueue_MultiSubscriber:
    """AlertQueue already uses asyncio.Lock. These benchmarks verify
    it holds up under multi-client concurrent drain patterns.
    """

    @pytest.mark.asyncio
    async def test_b4_01_concurrent_push_pop(self):
        """10 producers + 5 consumers — no alert lost or double-consumed."""
        q = AlertQueue(max_size=200)
        pushed = []
        popped = []

        async def producer(start: int):
            for i in range(10):
                alert = _make_alert(f"pa_{start}_{i}")
                await q.push(alert)
                pushed.append(alert.id)

        async def consumer():
            await asyncio.sleep(0.01)  # Let producers get ahead
            alerts = await q.pop_all()
            popped.extend([a.id for a in alerts])

        producers = [producer(s * 10) for s in range(10)]
        consumers = [consumer() for _ in range(5)]
        await asyncio.gather(*producers, *consumers)

        # Drain remaining
        remaining = await q.pop_all()
        popped.extend([a.id for a in remaining])

        # Every pushed alert should appear exactly once in popped
        assert len(popped) == len(pushed), (
            f"Pushed {len(pushed)}, popped {len(popped)}. "
            f"Lost: {len(pushed) - len(popped)}"
        )

    @pytest.mark.asyncio
    async def test_b4_02_concurrent_has_pending_during_drain(self):
        """has_pending() + pop_all() interleaved — no deadlock."""
        q = AlertQueue(max_size=50)
        for i in range(20):
            await q.push(_make_alert(f"pa_{i}"))

        async def checker():
            for _ in range(50):
                await q.has_pending()
                await asyncio.sleep(0)

        async def drainer():
            await asyncio.sleep(0.01)
            return await q.pop_all()

        results = await asyncio.gather(checker(), drainer(), checker())
        # drainer result is results[1]
        assert isinstance(results[1], list)

    @pytest.mark.asyncio
    async def test_b4_03_high_throughput_push(self):
        """500 pushes as fast as possible — bounded queue stays within limits."""
        q = AlertQueue(max_size=100)
        for i in range(500):
            await q.push(_make_alert(f"pa_{i}"))
        size = await q.size()
        assert size <= 100


# ===========================================================================
# B5 — Event Bus (NEW COMPONENT — does not exist yet)
# ===========================================================================

class TestB5_EventBus:
    """Event Bus for multi-subscriber alert routing.
    This component DOES NOT EXIST yet — these tests define the API.
    All tests in this section are expected to FAIL until implemented.
    """

    @pytest.mark.asyncio
    async def test_b5_01_subscribe_and_receive(self):
        """Single subscriber receives published events."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        received = []

        async def handler(event: dict):
            received.append(event)

        bus.subscribe("alert", handler)
        await bus.publish("alert", {"rule_id": "r_1", "message": "triggered"})
        await asyncio.sleep(0.01)  # Let handler run

        assert len(received) == 1
        assert received[0]["rule_id"] == "r_1"

    @pytest.mark.asyncio
    async def test_b5_02_multiple_subscribers(self):
        """Multiple subscribers all receive the same event."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        results = {"a": [], "b": [], "c": []}

        async def handler_a(event: dict):
            results["a"].append(event)

        async def handler_b(event: dict):
            results["b"].append(event)

        async def handler_c(event: dict):
            results["c"].append(event)

        bus.subscribe("alert", handler_a)
        bus.subscribe("alert", handler_b)
        bus.subscribe("alert", handler_c)

        await bus.publish("alert", {"msg": "test"})
        await asyncio.sleep(0.01)

        assert len(results["a"]) == 1
        assert len(results["b"]) == 1
        assert len(results["c"]) == 1

    @pytest.mark.asyncio
    async def test_b5_03_topic_isolation(self):
        """Subscribers only receive events for their topic."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        alert_events = []
        scene_events = []

        async def alert_handler(event: dict):
            alert_events.append(event)

        async def scene_handler(event: dict):
            scene_events.append(event)

        bus.subscribe("alert", alert_handler)
        bus.subscribe("scene_update", scene_handler)

        await bus.publish("alert", {"type": "alert"})
        await bus.publish("scene_update", {"type": "scene"})
        await asyncio.sleep(0.01)

        assert len(alert_events) == 1
        assert len(scene_events) == 1
        assert alert_events[0]["type"] == "alert"
        assert scene_events[0]["type"] == "scene"

    @pytest.mark.asyncio
    async def test_b5_04_unsubscribe(self):
        """Unsubscribed handlers stop receiving events."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        received = []

        async def handler(event: dict):
            received.append(event)

        sub_id = bus.subscribe("alert", handler)
        await bus.publish("alert", {"n": 1})
        await asyncio.sleep(0.01)
        assert len(received) == 1

        bus.unsubscribe(sub_id)
        await bus.publish("alert", {"n": 2})
        await asyncio.sleep(0.01)
        assert len(received) == 1  # No new events after unsubscribe

    @pytest.mark.asyncio
    async def test_b5_05_concurrent_publish_subscribe(self):
        """High-frequency publish while subscribers are being added/removed."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        total_received = {"count": 0}

        async def handler(event: dict):
            total_received["count"] += 1

        sub_ids = []
        for _ in range(10):
            sub_ids.append(bus.subscribe("alert", handler))

        async def publisher():
            for i in range(50):
                await bus.publish("alert", {"i": i})
                await asyncio.sleep(0)

        async def churn():
            """Add and remove subscribers during publishing."""
            for _ in range(20):
                sid = bus.subscribe("alert", handler)
                await asyncio.sleep(0)
                bus.unsubscribe(sid)

        await asyncio.gather(publisher(), churn())
        await asyncio.sleep(0.05)

        # At least 10 subscribers * 50 events = 500 (some churn adds more)
        assert total_received["count"] >= 400

    @pytest.mark.asyncio
    async def test_b5_06_handler_error_isolation(self):
        """A failing handler should not break other subscribers."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        good_events = []

        async def bad_handler(event: dict):
            raise ValueError("I crashed!")

        async def good_handler(event: dict):
            good_events.append(event)

        bus.subscribe("alert", bad_handler)
        bus.subscribe("alert", good_handler)

        await bus.publish("alert", {"msg": "test"})
        await asyncio.sleep(0.01)

        # Good handler should still receive despite bad handler crashing
        assert len(good_events) == 1


# ===========================================================================
# B6 — End-to-End Multi-Client Simulation
# ===========================================================================

class TestB6_EndToEnd_MultiClient:
    """Simulate multiple AI clients (Claude, ChatGPT, Cursor)
    all hitting the same physical-mcp daemon simultaneously.
    """

    @pytest.mark.asyncio
    async def test_b6_01_three_clients_add_rules_simultaneously(self):
        """3 clients each add 5 rules — all 15 should persist."""
        engine = RulesEngine()
        scene = SceneState()

        async def client(name: str, start: int):
            for i in range(5):
                rule = _make_rule(f"r_{name}_{i}")
                engine.add_rule(rule)
                await asyncio.sleep(0)

        await asyncio.gather(
            client("claude", 0),
            client("chatgpt", 5),
            client("cursor", 10),
        )

        rules = engine.list_rules()
        assert len(rules) == 15

    @pytest.mark.asyncio
    async def test_b6_02_concurrent_rule_eval_and_scene_update(self):
        """One client evaluates rules while another updates scene state."""
        engine = RulesEngine()
        for i in range(5):
            engine.add_rule(_make_rule(f"r_{i}", cooldown=0))
        scene = SceneState()
        all_alerts = []

        async def evaluator():
            for _ in range(20):
                evals = [_make_eval(f"r_{i % 5}") for i in range(5)]
                alerts = engine.process_evaluations(evals, scene)
                all_alerts.extend(alerts)
                await asyncio.sleep(0)

        async def scene_updater():
            for i in range(50):
                scene.update(f"scene_{i}", [f"obj_{i}"], i % 3, f"change_{i}")
                await asyncio.sleep(0)

        await asyncio.gather(evaluator(), scene_updater())
        # Should have generated some alerts without crashing
        assert len(all_alerts) > 0
        # Scene should have been updated 50 times
        assert scene.update_count == 50

    @pytest.mark.asyncio
    async def test_b6_03_alert_queue_multi_client_drain(self):
        """Perception loop pushes alerts, 3 clients try to drain simultaneously.
        Each alert should be consumed by exactly one client.
        """
        q = AlertQueue(max_size=100)

        # Simulate perception loop pushing alerts
        async def perception():
            for i in range(30):
                await q.push(_make_alert(f"pa_{i}"))
                await asyncio.sleep(0.001)

        all_consumed = {"claude": [], "chatgpt": [], "cursor": []}

        async def client_drain(name: str):
            for _ in range(10):
                alerts = await q.pop_all()
                all_consumed[name].extend([a.id for a in alerts])
                await asyncio.sleep(0.005)

        await asyncio.gather(
            perception(),
            client_drain("claude"),
            client_drain("chatgpt"),
            client_drain("cursor"),
        )
        # Drain remaining
        remaining = await q.pop_all()
        total = (
            len(all_consumed["claude"])
            + len(all_consumed["chatgpt"])
            + len(all_consumed["cursor"])
            + len(remaining)
        )
        assert total == 30, f"Expected 30 total alerts, got {total}"

        # No duplicates across clients
        all_ids = (
            all_consumed["claude"]
            + all_consumed["chatgpt"]
            + all_consumed["cursor"]
            + [a.id for a in remaining]
        )
        assert len(all_ids) == len(set(all_ids)), "Duplicate alert consumption detected!"

    @pytest.mark.asyncio
    async def test_b6_04_memory_concurrent_multi_client(self, tmp_path):
        """3 clients writing to memory file simultaneously."""
        mem = MemoryStore(str(tmp_path / "memory.md"))

        async def client_events(name: str):
            for i in range(10):
                mem.append_event(f"{name}_event_{i}")
                await asyncio.sleep(0)

        async def client_prefs(name: str):
            for i in range(5):
                mem.set_preference(f"{name}_pref_{i}", f"val_{i}")
                await asyncio.sleep(0)

        await asyncio.gather(
            client_events("claude"),
            client_events("chatgpt"),
            client_events("cursor"),
            client_prefs("claude"),
            client_prefs("chatgpt"),
        )

        content = mem.read_all()
        events = mem.get_recent_events(count=100)

        # All 30 events should be present (10 * 3 clients)
        assert len(events) == 30, (
            f"Expected 30 events, got {len(events)}. "
            f"Lost {30 - len(events)} events due to file race conditions."
        )

        # All 10 preferences should be present (5 * 2 clients)
        for name in ["claude", "chatgpt"]:
            for i in range(5):
                assert f"{name}_pref_{i}" in content, (
                    f"Preference {name}_pref_{i} lost in concurrent writes!"
                )

    @pytest.mark.asyncio
    async def test_b6_05_full_pipeline_stress(self):
        """Stress test: simulate 5 clients doing everything at once.
        - Each client adds rules, evaluates, updates scene, pushes/pops alerts
        - Nothing should crash, no data corruption
        """
        engine = RulesEngine()
        scene = SceneState()
        q = AlertQueue(max_size=200)
        errors = []

        async def full_client(client_id: int):
            try:
                # Add rules
                for i in range(3):
                    engine.add_rule(_make_rule(f"r_c{client_id}_{i}", cooldown=0))

                # Update scene
                for i in range(10):
                    scene.update(
                        f"client{client_id}_scene_{i}",
                        [f"obj_{i}"],
                        client_id,
                        f"change_{i}",
                    )
                    await asyncio.sleep(0)

                # Evaluate rules
                for i in range(5):
                    evals = [_make_eval(f"r_c{client_id}_{j}") for j in range(3)]
                    engine.process_evaluations(evals, scene)
                    await asyncio.sleep(0)

                # Push and pop alerts
                for i in range(5):
                    await q.push(_make_alert(f"pa_c{client_id}_{i}"))
                await q.pop_all()

                # List rules
                rules = engine.list_rules()
                assert isinstance(rules, list)

                # Read scene
                d = scene.to_dict()
                assert "summary" in d

            except Exception as e:
                errors.append(f"Client {client_id}: {e}")

        await asyncio.gather(*(full_client(i) for i in range(5)))

        assert len(errors) == 0, f"Errors in stress test: {errors}"
        assert len(engine.list_rules()) == 15  # 5 clients * 3 rules each
        assert scene.update_count == 50  # 5 clients * 10 updates each


# ===========================================================================
# Performance Benchmarks
# ===========================================================================

class TestPerformance:
    """Timing benchmarks — not correctness, just speed gates."""

    @pytest.mark.asyncio
    async def test_perf_rules_engine_1000_ops(self):
        """1000 add+list operations should complete in <1 second."""
        engine = RulesEngine()
        start = time.monotonic()
        for i in range(1000):
            engine.add_rule(_make_rule(f"r_{i}"))
            engine.list_rules()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"1000 ops took {elapsed:.2f}s (target: <1s)"

    @pytest.mark.asyncio
    async def test_perf_scene_state_1000_updates(self):
        """1000 scene updates should complete in <1 second."""
        state = SceneState()
        start = time.monotonic()
        for i in range(1000):
            state.update(f"scene_{i}", [f"obj_{i}"], i % 5, f"change_{i}")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"1000 updates took {elapsed:.2f}s (target: <1s)"

    @pytest.mark.asyncio
    async def test_perf_alert_queue_1000_push_pop(self):
        """1000 push+pop cycles should complete in <2 seconds."""
        q = AlertQueue(max_size=500)
        start = time.monotonic()
        for i in range(1000):
            await q.push(_make_alert(f"pa_{i}"))
            if i % 10 == 0:
                await q.pop_all()
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"1000 push/pop took {elapsed:.2f}s (target: <2s)"

    def test_perf_memory_store_100_writes(self, tmp_path):
        """100 sequential memory writes should complete in <5 seconds."""
        mem = MemoryStore(str(tmp_path / "memory.md"))
        start = time.monotonic()
        for i in range(100):
            mem.append_event(f"event_{i}")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"100 writes took {elapsed:.2f}s (target: <5s)"


# ===========================================================================
# S — STRESS TESTS (Real-World Scenarios)
#
# Each test documents:
#   Scenario:  What real usage it simulates
#   Scale:     N clients x M requests
#   Threshold: When does it break / what must hold
# ===========================================================================

class TestS_Stress:
    """Stress tests that push the system to realistic and extreme limits.

    ┌──────────┬───────────────────────────────────────────────┬──────────────┬──────────────────────────────┐
    │ Test     │ Real-World Scenario                           │ Scale        │ Pass Threshold               │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-01     │ Smart home: 10 rooms, each with an AI client  │ 10 clients   │ 0 rules lost from 100 total  │
    │          │ adding watch rules at startup                 │ x 10 rules   │                              │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-02     │ Office building: 50 cameras all detecting     │ 50 cameras   │ 0 lost scene updates,        │
    │          │ motion and updating scene state at once        │ x 20 updates │ update_count == 1000         │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-03     │ University campus: 20 security stations each  │ 20 threads   │ 0 events lost from 500,      │
    │          │ logging events to the shared memory file       │ x 25 events  │ all 500 persisted to disk    │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-04     │ Shopping mall: 100 AI assistants each getting │ 100 clients  │ 0 alerts duplicated,         │
    │          │ alerts from 5 cameras, draining alert queue    │ x 10 drains  │ 0 alerts lost                │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-05     │ Event venue: 30 subscribers (apps) listening  │ 30 subs      │ Each sub gets all 200 events,│
    │          │ for alerts across 200 rapid-fire detections    │ x 200 events │ total delivery = 6000        │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-06     │ Factory floor: 50 threads logging sensor data │ 50 threads   │ 0 data lost from 1000        │
    │          │ + preferences simultaneously                  │ x 20 writes  │ writes across 3 sections     │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-07     │ City-wide deployment: 200 clients doing       │ 200 clients  │ 0 crashes, 0 data loss,      │
    │          │ everything (rules + scene + alerts + memory +  │ x mixed ops  │ all counts exact             │
    │          │ events) all at the same time                  │              │                              │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-08     │ Rapid rule churn: IoT devices constantly      │ 100 clients  │ No RuntimeError,             │
    │          │ adding/removing rules while others evaluate    │ x 50 ops    │ engine stays consistent      │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-09     │ Peak hour: 100 cameras trigger at once,       │ 100 cameras  │ All 100 alerts pushed,       │
    │          │ 50 clients compete to drain the queue          │ 50 clients   │ each consumed exactly once   │
    ├──────────┼───────────────────────────────────────────────┼──────────────┼──────────────────────────────┤
    │ S-10     │ Sustained load: 50 threads hammer memory file │ 50 threads   │ 0 data loss after 60s of     │
    │          │ for 3 seconds non-stop (worst case I/O)        │ x 3 seconds  │ continuous contention        │
    └──────────┴───────────────────────────────────────────────┴──────────────┴──────────────────────────────┘
    """

    # -------------------------------------------------------------------
    # S-01: Smart home — 10 AI clients adding rules at startup
    # Scenario: A house with 10 rooms, each room has its own AI (Claude in
    #           kitchen, ChatGPT in garage, Cursor in office, etc.).
    #           At boot, every AI adds 10 watch rules simultaneously.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s01_smart_home_10_clients_10_rules(self):
        """10 clients x 10 rules = 100 rules. Zero rules may be lost."""
        engine = RulesEngine()
        N_CLIENTS = 10
        RULES_PER_CLIENT = 10

        async def client_boot(client_id: int):
            for r in range(RULES_PER_CLIENT):
                engine.add_rule(_make_rule(f"r_room{client_id}_{r}"))
                await asyncio.sleep(0)  # yield between adds

        await asyncio.gather(*(client_boot(c) for c in range(N_CLIENTS)))

        total = len(engine.list_rules())
        expected = N_CLIENTS * RULES_PER_CLIENT
        assert total == expected, (
            f"Smart home: {N_CLIENTS} AI clients added {RULES_PER_CLIENT} rules each. "
            f"Expected {expected} rules, got {total}. Lost {expected - total} rules!"
        )

    # -------------------------------------------------------------------
    # S-02: Office building — 50 cameras reporting scene changes
    # Scenario: 50 cameras across floors detect motion simultaneously.
    #           Each camera updates scene state 20 times in quick succession.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s02_office_50_cameras_20_updates(self):
        """50 cameras x 20 updates = 1000. Zero updates may be lost."""
        state = SceneState()
        N_CAMERAS = 50
        UPDATES_PER_CAM = 20

        async def camera_feed(cam_id: int):
            for i in range(UPDATES_PER_CAM):
                state.update(
                    summary=f"cam{cam_id}_frame_{i}",
                    objects=[f"person_{cam_id}"],
                    people_count=(cam_id % 5) + 1,
                    change_desc=f"motion_cam{cam_id}_{i}",
                )
                await asyncio.sleep(0)

        await asyncio.gather(*(camera_feed(c) for c in range(N_CAMERAS)))

        expected = N_CAMERAS * UPDATES_PER_CAM
        assert state.update_count == expected, (
            f"Office building: {N_CAMERAS} cameras x {UPDATES_PER_CAM} updates. "
            f"Expected update_count={expected}, got {state.update_count}. "
            f"Lost {expected - state.update_count} scene updates!"
        )
        # Change log should have all entries (capped at 200 by deque maxlen)
        log = state.get_change_log(minutes=60)
        assert len(log) == min(expected, 200)

    # -------------------------------------------------------------------
    # S-03: University campus — 20 stations logging to shared memory
    # Scenario: 20 security monitoring stations across a campus, each
    #           running its own thread and logging events to a single
    #           shared memory file.
    # -------------------------------------------------------------------
    def test_s03_campus_20_threads_25_events(self, tmp_path):
        """20 threads x 25 events = 500. Zero events may be lost to disk."""
        N_THREADS = 20
        EVENTS_PER_THREAD = 25
        total_expected = N_THREADS * EVENTS_PER_THREAD
        mem_path = str(tmp_path / "campus_memory.md")
        barrier = threading.Barrier(N_THREADS)

        def station_logger(station_id: int):
            mem = MemoryStore(mem_path)
            barrier.wait()
            for i in range(EVENTS_PER_THREAD):
                mem.append_event(f"station_{station_id}_alert_{i}")

        threads = [
            threading.Thread(target=station_logger, args=(s,))
            for s in range(N_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        mem = MemoryStore(mem_path)
        events = mem.get_recent_events(count=1000)
        assert len(events) == total_expected, (
            f"University campus: {N_THREADS} stations x {EVENTS_PER_THREAD} events. "
            f"Expected {total_expected} events on disk, got {len(events)}. "
            f"Lost {total_expected - len(events)} events!"
        )

    # -------------------------------------------------------------------
    # S-04: Shopping mall — 100 AI assistants competing for alerts
    # Scenario: Mall with 5 cameras. Perception loop detects 100 events.
    #           100 AI kiosk assistants all poll check_camera_alerts at once.
    #           Each alert must be consumed exactly once (no dupes, no loss).
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s04_mall_100_clients_drain_alerts(self):
        """100 alerts pushed, 100 clients drain. 0 duplicates, 0 lost."""
        q = AlertQueue(max_size=500)
        N_ALERTS = 100
        N_CLIENTS = 100

        # Push all alerts first (perception burst)
        for i in range(N_ALERTS):
            await q.push(_make_alert(f"pa_mall_{i}"))

        all_consumed: dict[int, list[str]] = {c: [] for c in range(N_CLIENTS)}

        async def client_poll(client_id: int):
            for _ in range(5):  # each client tries 5 times
                alerts = await q.pop_all()
                all_consumed[client_id].extend([a.id for a in alerts])
                await asyncio.sleep(0.001)

        await asyncio.gather(*(client_poll(c) for c in range(N_CLIENTS)))

        # Drain any remaining
        remaining = await q.pop_all()
        all_ids = []
        for c in range(N_CLIENTS):
            all_ids.extend(all_consumed[c])
        all_ids.extend([a.id for a in remaining])

        assert len(all_ids) == N_ALERTS, (
            f"Shopping mall: {N_ALERTS} alerts, {N_CLIENTS} clients polling. "
            f"Expected {N_ALERTS} total consumed, got {len(all_ids)}. "
            f"{'Lost' if len(all_ids) < N_ALERTS else 'Duplicated'} "
            f"{abs(N_ALERTS - len(all_ids))} alerts!"
        )
        assert len(all_ids) == len(set(all_ids)), (
            f"Duplicate alert detected! {len(all_ids)} total but only "
            f"{len(set(all_ids))} unique."
        )

    # -------------------------------------------------------------------
    # S-05: Event venue — 30 apps subscribed to rapid-fire alerts
    # Scenario: Concert venue with cameras. 200 detections fire in quick
    #           succession. 30 subscriber apps (phone alerts, dashboards,
    #           PA system, etc.) must ALL receive every event.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s05_venue_30_subs_200_events(self):
        """30 subscribers x 200 events = 6000 total deliveries."""
        from physical_mcp.events import EventBus

        bus = EventBus()
        N_SUBS = 30
        N_EVENTS = 200
        expected_total = N_SUBS * N_EVENTS

        counters: dict[int, int] = {s: 0 for s in range(N_SUBS)}

        def make_handler(sub_id: int):
            async def handler(event: dict):
                counters[sub_id] += 1
            return handler

        for s in range(N_SUBS):
            bus.subscribe("alert", make_handler(s))

        for i in range(N_EVENTS):
            await bus.publish("alert", {"detection": i})
            if i % 50 == 0:
                await asyncio.sleep(0)  # yield periodically

        await asyncio.sleep(0.1)  # let handlers finish

        total_delivered = sum(counters.values())
        for s in range(N_SUBS):
            assert counters[s] == N_EVENTS, (
                f"Event venue: subscriber {s} received {counters[s]}/{N_EVENTS} events. "
                f"Missed {N_EVENTS - counters[s]}!"
            )
        assert total_delivered == expected_total, (
            f"Event venue: {N_SUBS} subs x {N_EVENTS} events. "
            f"Expected {expected_total} deliveries, got {total_delivered}."
        )

    # -------------------------------------------------------------------
    # S-06: Factory floor — 50 threads writing sensor data + preferences
    # Scenario: Industrial deployment with 50 sensor nodes, each logging
    #           to memory (events, rule contexts, and preferences) from
    #           separate threads.
    # -------------------------------------------------------------------
    def test_s06_factory_50_threads_mixed_writes(self, tmp_path):
        """50 threads x 20 mixed writes = 1000. Zero data lost."""
        N_THREADS = 50
        WRITES_PER_THREAD = 20
        mem_path = str(tmp_path / "factory_memory.md")
        barrier = threading.Barrier(N_THREADS)

        def sensor_node(node_id: int):
            mem = MemoryStore(mem_path)
            barrier.wait()
            for i in range(WRITES_PER_THREAD):
                op = i % 3
                if op == 0:
                    mem.append_event(f"node{node_id}_reading_{i}")
                elif op == 1:
                    mem.set_rule_context(f"sensor_n{node_id}", f"threshold_{i}")
                else:
                    mem.set_preference(f"node{node_id}_cfg", f"val_{i}")

        threads = [
            threading.Thread(target=sensor_node, args=(n,))
            for n in range(N_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        mem = MemoryStore(mem_path)
        content = mem.read_all()
        events = mem.get_recent_events(count=2000)

        # Each thread writes ~7 events (indices 0,3,6,9,12,15,18 -> i%3==0)
        events_per_thread = len([i for i in range(WRITES_PER_THREAD) if i % 3 == 0])
        expected_events = N_THREADS * events_per_thread
        assert len(events) == expected_events, (
            f"Factory: {N_THREADS} threads x {events_per_thread} events each. "
            f"Expected {expected_events} events, got {len(events)}. "
            f"Lost {expected_events - len(events)} sensor readings!"
        )

        # Each thread should have its rule context (last write wins per key)
        for n in range(N_THREADS):
            assert f"sensor_n{n}" in content, (
                f"Factory: sensor node {n} rule context lost!"
            )

        # Each thread should have its preference
        for n in range(N_THREADS):
            assert f"node{n}_cfg" in content, (
                f"Factory: sensor node {n} preference lost!"
            )

    # -------------------------------------------------------------------
    # S-07: City-wide — 200 clients doing EVERYTHING simultaneously
    # Scenario: City-scale deployment. 200 AI clients (traffic cameras,
    #           street lights, transit, emergency services) all hitting
    #           one daemon. Each client adds rules, updates scene, pushes
    #           alerts, writes memory, and subscribes to events.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s07_citywide_200_clients_full_pipeline(self, tmp_path):
        """200 clients x all operations. 0 crashes, 0 data loss."""
        from physical_mcp.events import EventBus

        engine = RulesEngine()
        scene = SceneState()
        q = AlertQueue(max_size=2000)
        bus = EventBus()
        mem = MemoryStore(str(tmp_path / "city_memory.md"))
        N_CLIENTS = 200
        errors = []
        bus_received = {"count": 0}

        async def bus_handler(event: dict):
            bus_received["count"] += 1

        bus.subscribe("city_alert", bus_handler)

        async def city_client(cid: int):
            try:
                # 1. Add 2 watch rules
                for r in range(2):
                    engine.add_rule(_make_rule(f"r_city{cid}_{r}", cooldown=0))

                # 2. Update scene 3 times
                for i in range(3):
                    scene.update(f"city_c{cid}_{i}", [f"car_{cid}"], cid % 10, f"traffic_{cid}")
                    await asyncio.sleep(0)

                # 3. Push 2 alerts
                for i in range(2):
                    await q.push(_make_alert(f"pa_city{cid}_{i}"))

                # 4. Drain alerts
                await q.pop_all()

                # 5. Publish event
                await bus.publish("city_alert", {"client": cid})

                # 6. Write memory (asyncio context, so this is safe)
                mem.append_event(f"city_client_{cid}_connected")

                # 7. Read state
                engine.list_rules()
                scene.to_dict()

            except Exception as e:
                errors.append(f"Client {cid}: {type(e).__name__}: {e}")

        await asyncio.gather(*(city_client(c) for c in range(N_CLIENTS)))
        await asyncio.sleep(0.1)  # let bus handlers finish

        assert len(errors) == 0, (
            f"City-wide: {len(errors)}/{N_CLIENTS} clients crashed!\n"
            + "\n".join(errors[:10])
        )
        assert len(engine.list_rules()) == N_CLIENTS * 2, (
            f"City-wide: Expected {N_CLIENTS * 2} rules, "
            f"got {len(engine.list_rules())}."
        )
        assert scene.update_count == N_CLIENTS * 3, (
            f"City-wide: Expected {N_CLIENTS * 3} scene updates, "
            f"got {scene.update_count}."
        )
        assert bus_received["count"] == N_CLIENTS, (
            f"City-wide: EventBus expected {N_CLIENTS} events, "
            f"got {bus_received['count']}."
        )
        events = mem.get_recent_events(count=500)
        assert len(events) == N_CLIENTS, (
            f"City-wide: Expected {N_CLIENTS} memory events, "
            f"got {len(events)}."
        )

    # -------------------------------------------------------------------
    # S-08: Rapid rule churn — IoT devices constantly adding/removing
    # Scenario: 100 IoT devices that frequently reconfigure their watch
    #           rules (e.g., temperature thresholds change with time of
    #           day). While rules churn, other clients evaluate rules.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s08_iot_100_clients_rule_churn(self):
        """100 clients churning rules while 10 evaluators run. No crashes."""
        engine = RulesEngine()
        scene = SceneState(summary="factory floor")
        N_CHURNERS = 100
        N_EVALUATORS = 10
        OPS_PER_CHURNER = 50
        errors = []

        async def churner(cid: int):
            for i in range(OPS_PER_CHURNER):
                rule_id = f"r_iot{cid}_{i % 5}"
                try:
                    if i % 2 == 0:
                        engine.add_rule(_make_rule(rule_id, cooldown=0))
                    else:
                        engine.remove_rule(rule_id)
                except RuntimeError as e:
                    errors.append(f"Churner {cid}: {e}")
                await asyncio.sleep(0)

        async def evaluator(eid: int):
            for _ in range(100):
                try:
                    active = engine.get_active_rules()
                    if active:
                        evals = [_make_eval(active[0].id)]
                        engine.process_evaluations(evals, scene)
                    engine.list_rules()
                except RuntimeError as e:
                    errors.append(f"Evaluator {eid}: {e}")
                await asyncio.sleep(0)

        await asyncio.gather(
            *(churner(c) for c in range(N_CHURNERS)),
            *(evaluator(e) for e in range(N_EVALUATORS)),
        )

        assert len(errors) == 0, (
            f"Rule churn: {len(errors)} RuntimeErrors under {N_CHURNERS} "
            f"churners + {N_EVALUATORS} evaluators!\n" + "\n".join(errors[:5])
        )

    # -------------------------------------------------------------------
    # S-09: Peak hour — 100 cameras trigger, 50 clients compete to drain
    # Scenario: Rush hour at a transit hub. All 100 cameras detect events
    #           simultaneously. 50 dashboard clients all call
    #           check_camera_alerts at the same instant.
    # -------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_s09_peak_100_cameras_50_clients(self):
        """100 alerts, 50 clients racing to drain. 0 lost, 0 duplicated."""
        q = AlertQueue(max_size=500)
        N_ALERTS = 100
        N_CLIENTS = 50

        # All cameras fire at once
        for i in range(N_ALERTS):
            await q.push(_make_alert(f"pa_peak_{i}"))

        all_consumed: list[str] = []
        lock = asyncio.Lock()

        async def client_race(cid: int):
            for _ in range(3):
                alerts = await q.pop_all()
                async with lock:
                    all_consumed.extend([a.id for a in alerts])
                await asyncio.sleep(0)

        await asyncio.gather(*(client_race(c) for c in range(N_CLIENTS)))

        # Drain stragglers
        remaining = await q.pop_all()
        all_consumed.extend([a.id for a in remaining])

        assert len(all_consumed) == N_ALERTS, (
            f"Peak hour: {N_ALERTS} camera triggers, {N_CLIENTS} clients. "
            f"Expected {N_ALERTS} consumed, got {len(all_consumed)}. "
            f"{'Lost' if len(all_consumed) < N_ALERTS else 'Duplicated'} "
            f"{abs(N_ALERTS - len(all_consumed))} alerts!"
        )
        assert len(set(all_consumed)) == len(all_consumed), (
            f"Peak hour: Duplicate alerts! {len(all_consumed)} consumed "
            f"but {len(set(all_consumed))} unique."
        )

    # -------------------------------------------------------------------
    # S-10: Sustained load — 50 threads writing to memory for 3 seconds
    # Scenario: Worst-case I/O contention. 50 threads non-stop writing
    #           to the same memory file for 3 seconds straight.
    #           Simulates a burst of activity during a building-wide alarm.
    #           MemoryStore caps at 500 events (_MAX_EVENTS), so we verify:
    #           - File is never corrupted (valid markdown header)
    #           - Exactly 500 most-recent events survive (trimming works)
    #           - All threads contributed (no thread starved out)
    #           - Throughput is reported for performance visibility
    # -------------------------------------------------------------------
    def test_s10_sustained_50_threads_3_seconds(self, tmp_path):
        """50 threads writing non-stop for 3s. 0 corruption, correct trim."""
        N_THREADS = 50
        DURATION = 3.0
        MAX_EVENTS = 500  # MemoryStore._MAX_EVENTS
        mem_path = str(tmp_path / "sustained_memory.md")
        barrier = threading.Barrier(N_THREADS)
        write_counts: dict[int, int] = {}

        def sustained_writer(tid: int):
            mem = MemoryStore(mem_path)
            count = 0
            barrier.wait()
            deadline = time.monotonic() + DURATION
            while time.monotonic() < deadline:
                mem.append_event(f"t{tid}_sustained_{count}")
                count += 1
            write_counts[tid] = count

        threads = [
            threading.Thread(target=sustained_writer, args=(t,))
            for t in range(N_THREADS)
        ]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=DURATION + 30)
        elapsed = time.monotonic() - start

        total_written = sum(write_counts.values())
        mem = MemoryStore(mem_path)
        events = mem.get_recent_events(count=MAX_EVENTS + 100)

        # 1. File must not be corrupt
        content = mem.read_all()
        assert content.startswith("# Physical MCP Memory"), (
            f"Sustained load: Memory file corrupted! "
            f"Header: {content[:50]!r}"
        )

        # 2. Event count must be exactly MAX_EVENTS (trimmed correctly)
        assert len(events) == min(total_written, MAX_EVENTS), (
            f"Sustained load: {N_THREADS} threads x {DURATION}s. "
            f"Wrote {total_written} events, expected {MAX_EVENTS} after trim, "
            f"got {len(events)}. Trim logic broken under contention!"
        )

        # 3. All 50 threads must have written at least 1 event (no starvation)
        assert all(c > 0 for c in write_counts.values()), (
            f"Thread starvation! Some threads wrote 0 events: "
            f"{[t for t, c in write_counts.items() if c == 0]}"
        )

        # 4. Report throughput (informational, not a pass/fail gate)
        throughput = total_written / elapsed
        print(
            f"\n  Sustained load results: {N_THREADS} threads x {DURATION}s"
            f"\n  Total writes:  {total_written}"
            f"\n  Throughput:    {throughput:.0f} writes/sec"
            f"\n  Events kept:   {len(events)} (cap={MAX_EVENTS})"
            f"\n  Per-thread:    min={min(write_counts.values())}, "
            f"max={max(write_counts.values())}, "
            f"avg={total_written // N_THREADS}"
        )
