"""YAML persistence for watch rules."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import WatchRule


class RulesStore:
    """Load and save watch rules to a YAML file."""

    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser()

    def load(self) -> list[WatchRule]:
        if not self._path.exists():
            return []
        try:
            data = yaml.safe_load(self._path.read_text())
            if not data or "rules" not in data:
                return []
            return [WatchRule(**r) for r in data["rules"]]
        except Exception:
            return []

    def save(self, rules: list[WatchRule]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"rules": [r.model_dump(mode="json") for r in rules]}
        self._path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
