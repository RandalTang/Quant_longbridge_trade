from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStateStore:
    def __init__(self, path: str = ".data/alert_state.json") -> None:
        self.path = Path(path)

    def was_sent(self, key: str) -> bool:
        return key in self._read().get("sent_alerts", {})

    def mark_sent(self, key: str) -> None:
        state = self._read()
        sent = state.setdefault("sent_alerts", {})
        sent[key] = True
        self._write(state)

    def get(self, key: str) -> Any:
        return self._read().get(key)

    def set(self, key: str, value: Any) -> None:
        state = self._read()
        state[key] = value
        self._write(state)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
