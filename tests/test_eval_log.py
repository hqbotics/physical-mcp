"""Tests for EvalLog (SQLite evaluation log) and self-tuning feedback loop."""

from __future__ import annotations


import pytest

from physical_mcp.eval_log import EvalLog


@pytest.fixture
def eval_log(tmp_path):
    """Create an EvalLog instance with a temp database."""
    db_path = str(tmp_path / "test_eval_log.db")
    return EvalLog(path=db_path)


class TestEvalLog:
    """Tests for the EvalLog class."""

    def test_init_creates_db(self, eval_log):
        """EvalLog creates the database file on init."""
        assert eval_log._path.exists()

    def test_log_evaluation(self, eval_log):
        """log_evaluation inserts a row and returns an id."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_test1",
            rule_name="test rule",
            condition="someone drinks water",
            camera_id="cloud",
            triggered=True,
            confidence=0.85,
            reasoning="Person is holding a glass",
            scene_summary="A person at a desk",
        )
        assert isinstance(eval_id, int)
        assert eval_id > 0

    def test_get_eval_by_id(self, eval_log):
        """get_eval_by_id returns the inserted evaluation."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_test2",
            rule_name="cat on counter",
            condition="cat on the counter",
            camera_id="cloud",
            triggered=False,
            confidence=0.15,
            reasoning="No cat visible",
            scene_summary="Empty kitchen",
        )
        row = eval_log.get_eval_by_id(eval_id)
        assert row is not None
        assert row["rule_id"] == "r_test2"
        assert row["triggered"] == 0
        assert row["confidence"] == 0.15

    def test_record_feedback_correct(self, eval_log):
        """record_feedback updates TP counter for 'correct' on triggered eval."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_fb1",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.8,
            reasoning="test",
            scene_summary="test",
        )
        eval_log.record_feedback(eval_id, "correct")

        stats = eval_log.get_rule_stats("r_fb1")
        assert stats is not None
        assert stats["true_positives"] == 1
        assert stats["false_positives"] == 0
        assert stats["false_negatives"] == 0

    def test_record_feedback_wrong(self, eval_log):
        """record_feedback updates FP counter for 'wrong' on triggered eval."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_fb2",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.6,
            reasoning="test",
            scene_summary="test",
        )
        eval_log.record_feedback(eval_id, "wrong")

        stats = eval_log.get_rule_stats("r_fb2")
        assert stats is not None
        assert stats["true_positives"] == 0
        assert stats["false_positives"] == 1

    def test_record_feedback_missed(self, eval_log):
        """record_feedback updates FN counter for 'missed' feedback."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_fb3",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=False,
            confidence=0.1,
            reasoning="nothing visible",
            scene_summary="test",
        )
        eval_log.record_feedback(eval_id, "missed")

        stats = eval_log.get_rule_stats("r_fb3")
        assert stats is not None
        assert stats["false_negatives"] == 1

    def test_accuracy_calculation(self, eval_log):
        """accuracy is calculated correctly from TP/FP/FN counters."""
        rule_id = "r_acc"
        # 3 correct, 1 wrong = 3/(3+1+0) = 0.75
        for _ in range(3):
            eid = eval_log.log_evaluation(
                rule_id=rule_id,
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=True,
                confidence=0.8,
                reasoning="test",
                scene_summary="test",
            )
            eval_log.record_feedback(eid, "correct")

        eid = eval_log.log_evaluation(
            rule_id=rule_id,
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.5,
            reasoning="test",
            scene_summary="test",
        )
        eval_log.record_feedback(eid, "wrong")

        stats = eval_log.get_rule_stats(rule_id)
        assert stats is not None
        assert stats["accuracy"] == pytest.approx(0.75, abs=0.01)

    def test_get_recent_evals(self, eval_log):
        """get_recent_evals returns evaluations within the time window."""
        for i in range(5):
            eval_log.log_evaluation(
                rule_id="r_recent",
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=i % 2 == 0,
                confidence=0.5 + i * 0.1,
                reasoning=f"eval {i}",
                scene_summary="test",
            )

        recent = eval_log.get_recent_evals("r_recent", hours=1)
        assert len(recent) == 5

    def test_get_all_rule_stats(self, eval_log):
        """get_all_rule_stats returns stats for all rules with feedback."""
        for rid in ["r_a", "r_b"]:
            eid = eval_log.log_evaluation(
                rule_id=rid,
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=True,
                confidence=0.7,
                reasoning="test",
                scene_summary="test",
            )
            eval_log.record_feedback(eid, "correct")

        all_stats = eval_log.get_all_rule_stats()
        assert len(all_stats) == 2
        rule_ids = {s["rule_id"] for s in all_stats}
        assert "r_a" in rule_ids
        assert "r_b" in rule_ids

    def test_update_rule_tuning(self, eval_log):
        """update_rule_tuning changes threshold and hint."""
        eval_log.update_rule_tuning("r_tune", threshold=0.45, hint="Not phone")

        stats = eval_log.get_rule_stats("r_tune")
        assert stats is not None
        assert stats["confidence_threshold"] == 0.45
        assert stats["prompt_hint"] == "Not phone"

    def test_save_analysis_run(self, eval_log):
        """save_analysis_run records a self-analysis run."""
        run_id = eval_log.save_analysis_run(
            {
                "rule_id": "r_run",
                "window_hours": 24,
                "total_evals": 100,
                "triggered": 10,
                "feedback_count": 8,
                "fp_count": 2,
                "fn_count": 1,
                "old_threshold": 0.3,
                "new_threshold": 0.45,
                "old_hint": "",
                "new_hint": "Phone ≠ drinking",
                "llm_reasoning": "Too many false positives from phone usage",
            }
        )
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_prune_old_evaluations(self, eval_log):
        """prune removes old evaluations."""
        eval_log.log_evaluation(
            rule_id="r_prune",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=False,
            confidence=0.1,
            reasoning="test",
            scene_summary="test",
        )
        # Manually backdate the evaluation so prune can find it
        conn = eval_log._conn()
        conn.execute(
            "UPDATE evaluations SET ts = datetime('now', '-10 days') WHERE rule_id = 'r_prune'"
        )
        conn.commit()

        deleted = eval_log.prune(keep_days=7)
        assert deleted >= 1

    def test_db_size_bytes(self, eval_log):
        """db_size_bytes returns a positive number after writes."""
        eval_log.log_evaluation(
            rule_id="r_size",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=False,
            confidence=0.1,
            reasoning="test",
            scene_summary="test",
        )
        size = eval_log.db_size_bytes()
        assert size > 0


class TestEvalLogWithRulesEngine:
    """Test that RulesEngine correctly logs evaluations to EvalLog."""

    def test_rules_engine_logs_evaluations(self, eval_log):
        """RulesEngine logs all evaluations (triggered and not) to EvalLog."""
        from physical_mcp.perception.scene_state import SceneState
        from physical_mcp.rules.engine import RulesEngine
        from physical_mcp.rules.models import RuleEvaluation, WatchRule

        engine = RulesEngine(eval_log=eval_log)
        rule = WatchRule(
            id="r_eng1",
            name="test rule",
            condition="someone drinks water",
        )
        engine.add_rule(rule)

        evals = [
            RuleEvaluation(
                rule_id="r_eng1",
                triggered=True,
                confidence=0.85,
                reasoning="Person is drinking",
            )
        ]
        scene = SceneState()
        scene.update(
            summary="A person at a desk", objects=[], people_count=1, change_desc="none"
        )

        alerts = engine.process_evaluations(evals, scene, camera_id="cloud")
        assert len(alerts) == 1
        assert alerts[0].eval_id > 0

        # Check the eval was logged
        recent = eval_log.get_recent_evals("r_eng1", hours=1)
        assert len(recent) >= 1
        assert recent[0]["triggered"] == 1
        assert recent[0]["confidence"] == 0.85

    def test_per_rule_threshold_from_eval_log(self, eval_log):
        """RulesEngine uses per-rule threshold from EvalLog when available."""
        from physical_mcp.perception.scene_state import SceneState
        from physical_mcp.rules.engine import RulesEngine
        from physical_mcp.rules.models import RuleEvaluation, WatchRule

        # Set a high threshold for this rule
        eval_log.update_rule_tuning("r_thresh", threshold=0.8)

        engine = RulesEngine(eval_log=eval_log)
        rule = WatchRule(
            id="r_thresh",
            name="high threshold rule",
            condition="something happens",
        )
        engine.add_rule(rule)

        # This eval has confidence 0.5 — below the per-rule threshold of 0.8
        evals = [
            RuleEvaluation(
                rule_id="r_thresh",
                triggered=True,
                confidence=0.5,
                reasoning="Maybe happening",
            )
        ]
        scene = SceneState()
        scene.update(
            summary="Something", objects=[], people_count=0, change_desc="none"
        )

        alerts = engine.process_evaluations(evals, scene, camera_id="cloud")
        # Should be dropped because 0.5 < 0.8 threshold
        assert len(alerts) == 0

    def test_alert_event_has_eval_id(self, eval_log):
        """AlertEvent includes eval_id linking to the EvalLog."""
        from physical_mcp.perception.scene_state import SceneState
        from physical_mcp.rules.engine import RulesEngine
        from physical_mcp.rules.models import RuleEvaluation, WatchRule

        engine = RulesEngine(eval_log=eval_log)
        rule = WatchRule(
            id="r_eid",
            name="eval id test",
            condition="test condition",
        )
        engine.add_rule(rule)

        evals = [
            RuleEvaluation(
                rule_id="r_eid",
                triggered=True,
                confidence=0.9,
                reasoning="Clearly happening",
            )
        ]
        scene = SceneState()
        scene.update(
            summary="Test scene", objects=[], people_count=0, change_desc="none"
        )

        alerts = engine.process_evaluations(evals, scene, camera_id="cloud")
        assert len(alerts) == 1
        assert alerts[0].eval_id > 0

        # Verify it matches the logged evaluation
        row = eval_log.get_eval_by_id(alerts[0].eval_id)
        assert row is not None
        assert row["rule_id"] == "r_eid"


class TestTelegramFeedbackKeyboard:
    """Test that TelegramNotifier builds feedback keyboards."""

    def test_feedback_keyboard_with_eval_id(self):
        """Keyboard is built when eval_id is provided."""
        from physical_mcp.notifications.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test", default_chat_id="123")
        keyboard = notifier._build_feedback_keyboard(42)

        assert keyboard is not None
        assert len(keyboard) == 1  # One row
        assert len(keyboard[0]) == 3  # Three buttons
        assert "fb:42:correct" in keyboard[0][0]["callback_data"]
        assert "fb:42:wrong" in keyboard[0][1]["callback_data"]
        assert "fb:42:missed" in keyboard[0][2]["callback_data"]

    def test_no_keyboard_without_eval_id(self):
        """No keyboard when eval_id is 0."""
        from physical_mcp.notifications.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test", default_chat_id="123")
        keyboard = notifier._build_feedback_keyboard(0)
        assert keyboard is None


class TestFewShotExamples:
    """Test few-shot visual learning (example frame storage and retrieval)."""

    def test_save_example_frame(self, eval_log):
        """save_example_frame stores a thumbnail and returns a row id."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_fs1",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.85,
            reasoning="Person drinking",
            scene_summary="Kitchen",
        )
        row_id = eval_log.save_example_frame(
            eval_id=eval_id,
            rule_id="r_fs1",
            label="true_positive",
            thumbnail_bytes=b"\xff\xd8\xff\xe0fake_jpeg_data",
            reasoning="Person drinking water",
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_few_shot_examples_empty(self, eval_log):
        """get_few_shot_examples returns empty list when no examples exist."""
        examples = eval_log.get_few_shot_examples("r_nonexistent")
        assert examples == []

    def test_get_few_shot_examples_returns_tp(self, eval_log):
        """get_few_shot_examples returns TP example with b64 thumbnail."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_fs2",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.9,
            reasoning="Clear match",
            scene_summary="test",
        )
        eval_log.save_example_frame(
            eval_id=eval_id,
            rule_id="r_fs2",
            label="true_positive",
            thumbnail_bytes=b"jpeg_bytes_here",
            reasoning="Clear match",
        )
        examples = eval_log.get_few_shot_examples("r_fs2")
        assert len(examples) == 1
        assert examples[0]["label"] == "true_positive"
        assert examples[0]["thumbnail_b64"]  # non-empty base64
        assert examples[0]["reasoning"] == "Clear match"

    def test_get_few_shot_examples_returns_tp_and_fp(self, eval_log):
        """get_few_shot_examples returns both TP and FP examples."""
        for label, conf in [("true_positive", 0.9), ("false_positive", 0.4)]:
            eid = eval_log.log_evaluation(
                rule_id="r_fs3",
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=True,
                confidence=conf,
                reasoning=f"test {label}",
                scene_summary="test",
            )
            eval_log.save_example_frame(
                eval_id=eid,
                rule_id="r_fs3",
                label=label,
                thumbnail_bytes=f"thumb_{label}".encode(),
                reasoning=f"test {label}",
            )
        examples = eval_log.get_few_shot_examples("r_fs3")
        assert len(examples) == 2
        labels = {e["label"] for e in examples}
        assert "true_positive" in labels
        assert "false_positive" in labels

    def test_example_frame_cap_at_max(self, eval_log):
        """save_example_frame caps at _MAX_EXAMPLES_PER_LABEL per rule."""
        from physical_mcp.eval_log import _MAX_EXAMPLES_PER_LABEL

        for i in range(_MAX_EXAMPLES_PER_LABEL + 5):
            eid = eval_log.log_evaluation(
                rule_id="r_cap",
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=True,
                confidence=0.8,
                reasoning=f"eval {i}",
                scene_summary="test",
            )
            eval_log.save_example_frame(
                eval_id=eid,
                rule_id="r_cap",
                label="true_positive",
                thumbnail_bytes=f"thumb_{i}".encode(),
                reasoning=f"eval {i}",
            )

        counts = eval_log.get_example_count("r_cap")
        assert counts["true_positive"] == _MAX_EXAMPLES_PER_LABEL

    def test_feedback_saves_example_frame_from_thumbnail(self, eval_log):
        """record_feedback copies frame_thumbnail to example_frames."""
        thumb_data = b"\xff\xd8\xff\xe0fake_thumb"
        eval_id = eval_log.log_evaluation(
            rule_id="r_auto",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.85,
            reasoning="Person detected",
            scene_summary="Kitchen",
            frame_thumbnail=thumb_data,
        )
        eval_log.record_feedback(eval_id, "correct")

        examples = eval_log.get_few_shot_examples("r_auto")
        assert len(examples) == 1
        assert examples[0]["label"] == "true_positive"

    def test_feedback_wrong_saves_as_false_positive(self, eval_log):
        """Wrong feedback on triggered eval saves as false_positive."""
        thumb_data = b"thumb_data"
        eval_id = eval_log.log_evaluation(
            rule_id="r_fp",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.6,
            reasoning="Maybe drinking",
            scene_summary="test",
            frame_thumbnail=thumb_data,
        )
        eval_log.record_feedback(eval_id, "wrong")

        examples = eval_log.get_few_shot_examples("r_fp")
        assert len(examples) == 1
        assert examples[0]["label"] == "false_positive"

    def test_feedback_no_thumbnail_skips_example(self, eval_log):
        """No example saved when evaluation has no frame_thumbnail."""
        eval_id = eval_log.log_evaluation(
            rule_id="r_nothumb",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.8,
            reasoning="test",
            scene_summary="test",
            # No frame_thumbnail
        )
        eval_log.record_feedback(eval_id, "correct")

        examples = eval_log.get_few_shot_examples("r_nothumb")
        assert len(examples) == 0

    def test_get_example_count(self, eval_log):
        """get_example_count returns correct per-label counts."""
        for label in ["true_positive", "true_positive", "false_positive"]:
            eid = eval_log.log_evaluation(
                rule_id="r_cnt",
                rule_name="test",
                condition="test",
                camera_id="cloud",
                triggered=True,
                confidence=0.8,
                reasoning="test",
                scene_summary="test",
            )
            eval_log.save_example_frame(
                eval_id=eid,
                rule_id="r_cnt",
                label=label,
                thumbnail_bytes=b"thumb",
                reasoning="test",
            )
        counts = eval_log.get_example_count("r_cnt")
        assert counts["true_positive"] == 2
        assert counts["false_positive"] == 1

    def test_frame_thumbnail_stored_in_evaluation(self, eval_log):
        """frame_thumbnail BLOB is stored and retrievable."""
        thumb = b"\xff\xd8test_thumb_data"
        eval_id = eval_log.log_evaluation(
            rule_id="r_blob",
            rule_name="test",
            condition="test",
            camera_id="cloud",
            triggered=True,
            confidence=0.9,
            reasoning="test",
            scene_summary="test",
            frame_thumbnail=thumb,
        )
        row = eval_log.get_eval_by_id(eval_id)
        assert row is not None
        assert row["frame_thumbnail"] == thumb


class TestFewShotPrefix:
    """Test the few-shot prefix builder in analyzer."""

    def test_build_few_shot_prefix_with_examples(self):
        """_build_few_shot_prefix creates labeled text for reference images."""
        from physical_mcp.reasoning.analyzer import _build_few_shot_prefix

        examples = [
            {
                "label": "true_positive",
                "thumbnail_b64": "abc123",
                "reasoning": "Person is drinking water",
            },
            {
                "label": "false_positive",
                "thumbnail_b64": "def456",
                "reasoning": "Phone near face, not drinking",
            },
        ]
        prefix = _build_few_shot_prefix(examples)
        assert "REFERENCE EXAMPLES" in prefix
        assert "CORRECT DETECTION" in prefix
        assert "FALSE ALARM" in prefix
        assert "Person is drinking water" in prefix
        assert "Phone near face" in prefix
        assert "Reference image 1" in prefix
        assert "Reference image 2" in prefix

    def test_build_few_shot_prefix_empty(self):
        """_build_few_shot_prefix returns empty string for no examples."""
        from physical_mcp.reasoning.analyzer import _build_few_shot_prefix

        assert _build_few_shot_prefix([]) == ""


class TestPromptHints:
    """Test that rule hints are injected into LLM prompts."""

    def test_combined_prompt_with_hints(self):
        """build_combined_prompt includes hints when provided."""
        from physical_mcp.perception.scene_state import SceneState
        from physical_mcp.reasoning.prompts import build_combined_prompt
        from physical_mcp.rules.models import WatchRule

        rules = [
            WatchRule(id="r_1", name="drinking", condition="someone drinks water"),
            WatchRule(id="r_2", name="cat", condition="cat on counter"),
        ]
        hints = {"r_1": "Phone near face is NOT drinking"}

        prompt = build_combined_prompt(
            SceneState(), rules, frame_count=1, rule_hints=hints
        )

        assert "Phone near face is NOT drinking" in prompt
        assert '"hint":' in prompt

    def test_combined_prompt_without_hints(self):
        """build_combined_prompt works without hints."""
        from physical_mcp.perception.scene_state import SceneState
        from physical_mcp.reasoning.prompts import build_combined_prompt
        from physical_mcp.rules.models import WatchRule

        rules = [
            WatchRule(id="r_1", name="drinking", condition="someone drinks water"),
        ]

        prompt = build_combined_prompt(SceneState(), rules, frame_count=1)
        assert '"hint"' not in prompt
        assert "someone drinks water" in prompt
