"""Rolling scene state summary manager."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ChangeLogEntry:
    timestamp: datetime
    description: str


@dataclass
class SceneState:
    """Rolling summary of what the camera currently sees."""

    summary: str = ""
    objects_present: list[str] = field(default_factory=list)
    people_count: int = 0
    last_updated: datetime | None = None
    last_change_description: str = ""
    update_count: int = 0
    _change_log: deque[ChangeLogEntry] = field(
        default_factory=lambda: deque(maxlen=200)
    )

    def update(
        self, summary: str, objects: list[str], people_count: int, change_desc: str
    ) -> None:
        self.summary = summary
        self.objects_present = objects
        self.people_count = people_count
        self.last_updated = datetime.now()
        self.last_change_description = change_desc
        self.update_count += 1
        self._change_log.append(
            ChangeLogEntry(timestamp=datetime.now(), description=change_desc)
        )

    def record_change(self, description: str) -> None:
        """Record a change without full LLM analysis."""
        self._change_log.append(
            ChangeLogEntry(timestamp=datetime.now(), description=description)
        )

    def get_change_log(self, minutes: int = 5) -> list[dict]:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [
            {"timestamp": e.timestamp.isoformat(), "description": e.description}
            for e in self._change_log
            if e.timestamp >= cutoff
        ]

    def to_context_string(self) -> str:
        """Format state for injection into LLM context."""
        return (
            f"Current scene: {self.summary}\n"
            f"Objects: {', '.join(self.objects_present) if self.objects_present else 'unknown'}\n"
            f"People visible: {self.people_count}\n"
            f"Last change: {self.last_change_description}\n"
            f"Updated: {self.last_updated.isoformat() if self.last_updated else 'never'}\n"
            f"Total updates: {self.update_count}"
        )

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "objects_present": self.objects_present,
            "people_count": self.people_count,
            "last_updated": self.last_updated.isoformat()
            if self.last_updated
            else None,
            "last_change": self.last_change_description,
            "update_count": self.update_count,
        }
