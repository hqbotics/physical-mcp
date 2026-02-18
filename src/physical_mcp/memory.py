"""Markdown-based persistent memory for cross-session continuity.

Stores event history, rule context, and user preferences in a
human-readable markdown file at ~/.physical-mcp/memory.md.

The LLM client reads this on connect to understand what happened
in previous sessions (e.g., "user asked to alert when water runs
out a month ago").
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

# Section headers in the memory file
_HEADER = "# Physical MCP Memory"
_EVENT_LOG = "## Event Log"
_RULE_CONTEXT = "## Rule Context"
_PREFERENCES = "## User Preferences"
_MAX_EVENTS = 500

# Process-local locks keyed by memory file path to prevent thread races
# in read-modify-write operations.
_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_for_path(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[key] = lock
        return lock


class MemoryStore:
    """Append-only markdown memory file.

    Three sections:
    - Event Log: timestamped events (alerts, rule changes, observations)
    - Rule Context: why each rule was created (keyed by rule_id)
    - User Preferences: learned user preferences
    """

    def __init__(self, path: str = "~/.physical-mcp/memory.md"):
        self._path = Path(path).expanduser()
        self._lock = _lock_for_path(self._path)

    def read_all(self) -> str:
        """Return entire memory file as string."""
        with self._lock:
            if not self._path.exists():
                return ""
            return self._path.read_text()

    def append_event(self, event: str) -> None:
        """Append a timestamped line to the Event Log section."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- {ts} | {event}"
        with self._lock:
            self._ensure_file()
            sections = self._parse()
            sections["events"].append(line)
            # Trim to max size
            if len(sections["events"]) > _MAX_EVENTS:
                sections["events"] = sections["events"][-_MAX_EVENTS:]
            self._write(sections)

    def set_rule_context(self, rule_id: str, context: str) -> None:
        """Store why a rule was created. Overwrites previous entry for same rule_id."""
        with self._lock:
            self._ensure_file()
            sections = self._parse()
            # Remove existing entry for this rule_id
            sections["rules"] = [
                l for l in sections["rules"]
                if not l.startswith(f"- {rule_id} |")
            ]
            sections["rules"].append(f"- {rule_id} | {context}")
            self._write(sections)

    def remove_rule_context(self, rule_id: str) -> None:
        """Remove context when a rule is deleted."""
        with self._lock:
            if not self._path.exists():
                return
            sections = self._parse()
            sections["rules"] = [
                l for l in sections["rules"]
                if not l.startswith(f"- {rule_id} |")
            ]
            self._write(sections)

    def set_preference(self, key: str, value: str) -> None:
        """Store a user preference."""
        with self._lock:
            self._ensure_file()
            sections = self._parse()
            sections["prefs"] = [
                l for l in sections["prefs"]
                if not l.startswith(f"- {key} |")
            ]
            sections["prefs"].append(f"- {key} | {value}")
            self._write(sections)

    def get_recent_events(self, count: int = 50) -> list[str]:
        """Return last N event log lines."""
        with self._lock:
            if not self._path.exists():
                return []
            sections = self._parse()
            return sections["events"][-count:]

    def _ensure_file(self) -> None:
        """Create the memory file with empty sections if it doesn't exist."""
        if self._path.exists():
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write({"events": [], "rules": [], "prefs": []})

    def _parse(self) -> dict[str, list[str]]:
        """Parse the markdown file into sections."""
        if not self._path.exists():
            return {"events": [], "rules": [], "prefs": []}

        text = self._path.read_text()
        sections: dict[str, list[str]] = {"events": [], "rules": [], "prefs": []}
        current = None

        for line in text.splitlines():
            stripped = line.strip()
            if stripped == _EVENT_LOG:
                current = "events"
            elif stripped == _RULE_CONTEXT:
                current = "rules"
            elif stripped == _PREFERENCES:
                current = "prefs"
            elif stripped.startswith("# "):
                current = None  # Skip top-level header
            elif current and stripped.startswith("- "):
                sections[current].append(stripped)

        return sections

    def _write(self, sections: dict[str, list[str]]) -> None:
        """Write sections back to the markdown file."""
        lines = [_HEADER, ""]
        lines.append(_EVENT_LOG)
        for entry in sections["events"]:
            lines.append(entry)
        lines.append("")
        lines.append(_RULE_CONTEXT)
        for entry in sections["rules"]:
            lines.append(entry)
        lines.append("")
        lines.append(_PREFERENCES)
        for entry in sections["prefs"]:
            lines.append(entry)
        lines.append("")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("\n".join(lines))
