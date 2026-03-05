"""Persistent evaluation log backed by SQLite.

Records every LLM rule evaluation (triggered and not triggered),
user feedback on alerts, and self-analysis results.  Lives at
~/.physical-mcp/eval_log.db on the Fly.io persistent volume.

Also stores few-shot example frames (confirmed TP/FP/FN from user
feedback) for visual learning — these are included in future LLM
evaluation calls to improve accuracy.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("physical-mcp")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL DEFAULT (datetime('now')),
    rule_id       TEXT NOT NULL,
    rule_name     TEXT NOT NULL DEFAULT '',
    condition     TEXT NOT NULL DEFAULT '',
    camera_id     TEXT NOT NULL DEFAULT '',
    triggered     INTEGER NOT NULL,
    confidence    REAL NOT NULL,
    reasoning     TEXT NOT NULL DEFAULT '',
    scene_summary TEXT NOT NULL DEFAULT '',
    frame_hash    TEXT NOT NULL DEFAULT '',
    eval_source   TEXT NOT NULL DEFAULT 'server',
    frame_thumbnail BLOB
);

CREATE TABLE IF NOT EXISTS feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL DEFAULT (datetime('now')),
    eval_id             INTEGER NOT NULL,
    telegram_message_id INTEGER,
    chat_id             TEXT NOT NULL DEFAULT '',
    feedback            TEXT NOT NULL,
    FOREIGN KEY (eval_id) REFERENCES evaluations(id)
);

CREATE TABLE IF NOT EXISTS rule_tuning (
    rule_id              TEXT PRIMARY KEY,
    confidence_threshold REAL NOT NULL DEFAULT 0.3,
    prompt_hint          TEXT NOT NULL DEFAULT '',
    total_evals          INTEGER NOT NULL DEFAULT 0,
    true_positives       INTEGER NOT NULL DEFAULT 0,
    false_positives      INTEGER NOT NULL DEFAULT 0,
    false_negatives      INTEGER NOT NULL DEFAULT 0,
    last_tuned           TEXT,
    accuracy             REAL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL DEFAULT (datetime('now')),
    rule_id        TEXT NOT NULL,
    window_hours   INTEGER NOT NULL DEFAULT 24,
    total_evals    INTEGER NOT NULL DEFAULT 0,
    triggered      INTEGER NOT NULL DEFAULT 0,
    feedback_count INTEGER NOT NULL DEFAULT 0,
    fp_count       INTEGER NOT NULL DEFAULT 0,
    fn_count       INTEGER NOT NULL DEFAULT 0,
    old_threshold  REAL,
    new_threshold  REAL,
    old_hint       TEXT NOT NULL DEFAULT '',
    new_hint       TEXT NOT NULL DEFAULT '',
    llm_reasoning  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS example_frames (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL DEFAULT (datetime('now')),
    rule_id   TEXT NOT NULL,
    eval_id   INTEGER NOT NULL,
    label     TEXT NOT NULL,
    thumbnail BLOB NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (eval_id) REFERENCES evaluations(id)
);

CREATE INDEX IF NOT EXISTS idx_eval_rule_ts ON evaluations(rule_id, ts);
CREATE INDEX IF NOT EXISTS idx_eval_ts ON evaluations(ts);
CREATE INDEX IF NOT EXISTS idx_feedback_eval ON feedback(eval_id);
CREATE INDEX IF NOT EXISTS idx_example_rule ON example_frames(rule_id, label);
"""

# Maximum number of example frames stored per rule per label
_MAX_EXAMPLES_PER_LABEL = 20


class EvalLog:
    """Thread-safe SQLite evaluation log."""

    def __init__(self, path: str = "~/.physical-mcp/eval_log.db"):
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        conn = self._conn()
        conn.executescript(_SCHEMA)
        # Migrate existing databases: add columns/tables that may not exist
        self._migrate(conn)
        conn.commit()
        logger.info(f"EvalLog initialized at {self._path}")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns/tables for existing databases."""
        # Add frame_thumbnail column if missing (added in v1.3)
        try:
            conn.execute("SELECT frame_thumbnail FROM evaluations LIMIT 0")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE evaluations ADD COLUMN frame_thumbnail BLOB")
            logger.info("EvalLog: migrated evaluations table (added frame_thumbnail)")
        # example_frames table is created by _SCHEMA (IF NOT EXISTS)

    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._path), timeout=5.0)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=3000")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def log_evaluation(
        self,
        rule_id: str,
        rule_name: str,
        condition: str,
        camera_id: str,
        triggered: bool,
        confidence: float,
        reasoning: str,
        scene_summary: str,
        frame_bytes: bytes | None = None,
        eval_source: str = "server",
        frame_thumbnail: bytes | None = None,
    ) -> int:
        """Insert an evaluation record.  Returns the row id.

        frame_thumbnail: optional JPEG bytes of the frame at evaluation time.
            Stored only for alert-generating evaluations so feedback can
            copy it into the few-shot ``example_frames`` table.
        """
        frame_hash = ""
        if frame_bytes:
            frame_hash = hashlib.sha256(frame_bytes).hexdigest()[:16]

        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO evaluations
               (rule_id, rule_name, condition, camera_id,
                triggered, confidence, reasoning, scene_summary,
                frame_hash, eval_source, frame_thumbnail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule_id,
                rule_name,
                condition,
                camera_id,
                int(triggered),
                confidence,
                reasoning,
                scene_summary,
                frame_hash,
                eval_source,
                frame_thumbnail,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def record_feedback(
        self,
        eval_id: int,
        feedback: str,
        telegram_message_id: int | None = None,
        chat_id: str = "",
    ) -> None:
        """Record user feedback for an evaluation.

        Also copies the evaluation's frame thumbnail (if any) into the
        ``example_frames`` table so it can be used as a few-shot visual
        example in future LLM calls.
        """
        conn = self._conn()
        conn.execute(
            """INSERT INTO feedback (eval_id, feedback, telegram_message_id, chat_id)
               VALUES (?, ?, ?, ?)""",
            (eval_id, feedback, telegram_message_id, chat_id),
        )
        conn.commit()

        row = conn.execute(
            "SELECT rule_id, triggered, reasoning, frame_thumbnail FROM evaluations WHERE id = ?",
            (eval_id,),
        ).fetchone()
        if row:
            self._update_tuning_counters(
                row["rule_id"], feedback, bool(row["triggered"])
            )
            # Save frame as few-shot example if thumbnail exists
            if row["frame_thumbnail"]:
                label = self._feedback_to_label(feedback, bool(row["triggered"]))
                if label:
                    self.save_example_frame(
                        eval_id=eval_id,
                        rule_id=row["rule_id"],
                        label=label,
                        thumbnail_bytes=row["frame_thumbnail"],
                        reasoning=row["reasoning"] or "",
                    )

    @staticmethod
    def _feedback_to_label(feedback: str, was_triggered: bool) -> str | None:
        """Map feedback type to example label."""
        if feedback == "correct" and was_triggered:
            return "true_positive"
        elif feedback == "wrong" and was_triggered:
            return "false_positive"
        elif feedback == "missed":
            return "false_negative"
        return None

    def _update_tuning_counters(
        self, rule_id: str, feedback: str, was_triggered: bool
    ) -> None:
        """Increment TP/FP/FN counters in rule_tuning."""
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO rule_tuning (rule_id) VALUES (?)",
            (rule_id,),
        )
        if feedback == "correct" and was_triggered:
            conn.execute(
                "UPDATE rule_tuning SET true_positives = true_positives + 1, "
                "total_evals = total_evals + 1 WHERE rule_id = ?",
                (rule_id,),
            )
        elif feedback == "wrong" and was_triggered:
            conn.execute(
                "UPDATE rule_tuning SET false_positives = false_positives + 1, "
                "total_evals = total_evals + 1 WHERE rule_id = ?",
                (rule_id,),
            )
        elif feedback == "missed":
            conn.execute(
                "UPDATE rule_tuning SET false_negatives = false_negatives + 1, "
                "total_evals = total_evals + 1 WHERE rule_id = ?",
                (rule_id,),
            )
        conn.execute(
            """UPDATE rule_tuning SET accuracy =
               CASE WHEN (true_positives + false_positives + false_negatives) > 0
               THEN CAST(true_positives AS REAL) /
                    (true_positives + false_positives + false_negatives)
               ELSE NULL END
               WHERE rule_id = ?""",
            (rule_id,),
        )
        conn.commit()

    def get_rule_stats(self, rule_id: str) -> dict | None:
        """Get tuning stats for a rule."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM rule_tuning WHERE rule_id = ?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_rule_stats(self) -> list[dict]:
        """Get tuning stats for all rules."""
        conn = self._conn()
        rows = conn.execute("SELECT * FROM rule_tuning ORDER BY rule_id").fetchall()
        return [dict(r) for r in rows]

    def get_recent_evals(
        self, rule_id: str, hours: int = 24, limit: int = 200
    ) -> list[dict]:
        """Get recent evaluations for a rule with optional feedback."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT e.*, f.feedback
               FROM evaluations e
               LEFT JOIN feedback f ON f.eval_id = e.id
               WHERE e.rule_id = ?
               AND e.ts >= datetime('now', ?)
               ORDER BY e.ts DESC LIMIT ?""",
            (rule_id, f"-{hours} hours", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_eval_by_id(self, eval_id: int) -> dict | None:
        """Get a single evaluation by id."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM evaluations WHERE id = ?", (eval_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── Few-shot visual learning ──────────────────────────────

    def save_example_frame(
        self,
        eval_id: int,
        rule_id: str,
        label: str,
        thumbnail_bytes: bytes,
        reasoning: str = "",
    ) -> int:
        """Save a frame thumbnail as a few-shot example for a rule.

        Caps at ``_MAX_EXAMPLES_PER_LABEL`` per rule per label by removing
        the oldest entries when the limit is exceeded.
        """
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO example_frames
               (rule_id, eval_id, label, thumbnail, reasoning)
               VALUES (?, ?, ?, ?, ?)""",
            (rule_id, eval_id, label, thumbnail_bytes, reasoning),
        )
        conn.commit()
        row_id = cur.lastrowid

        # Prune oldest if over limit
        count = conn.execute(
            "SELECT COUNT(*) FROM example_frames WHERE rule_id = ? AND label = ?",
            (rule_id, label),
        ).fetchone()[0]
        if count > _MAX_EXAMPLES_PER_LABEL:
            excess = count - _MAX_EXAMPLES_PER_LABEL
            conn.execute(
                """DELETE FROM example_frames WHERE id IN (
                       SELECT id FROM example_frames
                       WHERE rule_id = ? AND label = ?
                       ORDER BY ts ASC LIMIT ?
                   )""",
                (rule_id, label, excess),
            )
            conn.commit()

        logger.info(
            f"Saved {label} example for rule {rule_id} "
            f"({len(thumbnail_bytes)} bytes, eval #{eval_id})"
        )
        return row_id  # type: ignore[return-value]

    def get_few_shot_examples(
        self,
        rule_id: str,
        max_per_label: int = 1,
    ) -> list[dict]:
        """Get the best few-shot examples for a rule.

        Returns up to ``max_per_label`` examples for each label type
        (true_positive, false_positive, false_negative).

        Selection strategy:
        - true_positive: highest confidence (most clear-cut correct detection)
        - false_positive: most recent (most relevant mistake to avoid)
        - false_negative: most recent (most relevant miss)

        Returns list of dicts with keys:
            label, thumbnail_b64, reasoning
        """
        conn = self._conn()
        results: list[dict] = []

        # Best TP: highest-confidence true positive
        tp_rows = conn.execute(
            """SELECT ef.*, e.confidence FROM example_frames ef
               JOIN evaluations e ON e.id = ef.eval_id
               WHERE ef.rule_id = ? AND ef.label = 'true_positive'
               ORDER BY e.confidence DESC LIMIT ?""",
            (rule_id, max_per_label),
        ).fetchall()
        for row in tp_rows:
            results.append(
                {
                    "label": "true_positive",
                    "thumbnail_b64": base64.b64encode(row["thumbnail"]).decode(),
                    "reasoning": row["reasoning"],
                }
            )

        # Most recent FP
        fp_rows = conn.execute(
            """SELECT * FROM example_frames
               WHERE rule_id = ? AND label = 'false_positive'
               ORDER BY ts DESC LIMIT ?""",
            (rule_id, max_per_label),
        ).fetchall()
        for row in fp_rows:
            results.append(
                {
                    "label": "false_positive",
                    "thumbnail_b64": base64.b64encode(row["thumbnail"]).decode(),
                    "reasoning": row["reasoning"],
                }
            )

        # Most recent FN
        fn_rows = conn.execute(
            """SELECT * FROM example_frames
               WHERE rule_id = ? AND label = 'false_negative'
               ORDER BY ts DESC LIMIT ?""",
            (rule_id, max_per_label),
        ).fetchall()
        for row in fn_rows:
            results.append(
                {
                    "label": "false_negative",
                    "thumbnail_b64": base64.b64encode(row["thumbnail"]).decode(),
                    "reasoning": row["reasoning"],
                }
            )

        return results

    def get_example_count(self, rule_id: str | None = None) -> dict:
        """Get count of example frames, optionally filtered by rule."""
        conn = self._conn()
        if rule_id:
            rows = conn.execute(
                "SELECT label, COUNT(*) as cnt FROM example_frames "
                "WHERE rule_id = ? GROUP BY label",
                (rule_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT label, COUNT(*) as cnt FROM example_frames GROUP BY label"
            ).fetchall()
        return {row["label"]: row["cnt"] for row in rows}

    def prune(self, keep_days: int = 7) -> int:
        """Delete evaluations older than keep_days.  Returns count deleted.

        Note: example_frames are NOT pruned here — they are long-lived
        few-shot examples and are capped per-rule in save_example_frame().
        Frame thumbnails on evaluations older than keep_days are cleared
        as part of the evaluation deletion.
        """
        conn = self._conn()
        # Clear frame thumbnails on evaluations older than 2 days
        # (but keep the text metadata until keep_days)
        conn.execute(
            "UPDATE evaluations SET frame_thumbnail = NULL "
            "WHERE frame_thumbnail IS NOT NULL AND ts < datetime('now', '-2 days')"
        )
        cur = conn.execute(
            "DELETE FROM evaluations WHERE ts < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        conn.execute(
            "DELETE FROM feedback WHERE eval_id NOT IN (SELECT id FROM evaluations)"
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info(f"EvalLog pruned {deleted} old evaluations (>{keep_days} days)")
        return deleted

    def save_analysis_run(self, run: dict) -> int:
        """Record a self-analysis run."""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO analysis_runs
               (rule_id, window_hours, total_evals, triggered,
                feedback_count, fp_count, fn_count,
                old_threshold, new_threshold, old_hint, new_hint, llm_reasoning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run["rule_id"],
                run.get("window_hours", 24),
                run.get("total_evals", 0),
                run.get("triggered", 0),
                run.get("feedback_count", 0),
                run.get("fp_count", 0),
                run.get("fn_count", 0),
                run.get("old_threshold"),
                run.get("new_threshold"),
                run.get("old_hint", ""),
                run.get("new_hint", ""),
                run.get("llm_reasoning", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_rule_tuning(
        self,
        rule_id: str,
        threshold: float | None = None,
        hint: str | None = None,
    ) -> None:
        """Update per-rule confidence threshold and/or prompt hint."""
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO rule_tuning (rule_id) VALUES (?)",
            (rule_id,),
        )
        if threshold is not None:
            conn.execute(
                "UPDATE rule_tuning SET confidence_threshold = ?, "
                "last_tuned = datetime('now') WHERE rule_id = ?",
                (threshold, rule_id),
            )
        if hint is not None:
            conn.execute(
                "UPDATE rule_tuning SET prompt_hint = ?, "
                "last_tuned = datetime('now') WHERE rule_id = ?",
                (hint, rule_id),
            )
        conn.commit()

    def db_size_bytes(self) -> int:
        """Return the size of the database file in bytes."""
        return self._path.stat().st_size if self._path.exists() else 0
