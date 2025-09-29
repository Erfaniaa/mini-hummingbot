from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


class SettingsStore:
    """Persist and retrieve last-used settings per strategy name.

    Stores JSON files under a directory (default: settings/).
    Does not store sensitive data (no private keys), only user selections.
    """

    def __init__(self, dir_path: str) -> None:
        self.dir_path = os.path.abspath(dir_path)

    def _path(self, strategy_name: str) -> str:
        safe = "".join(c for c in strategy_name if c.isalnum() or c in ("_", "-"))
        return os.path.join(self.dir_path, f"{safe}.json")

    def load(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._path(strategy_name)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save(self, strategy_name: str, data: Dict[str, Any]) -> None:
        os.makedirs(self.dir_path, exist_ok=True)
        path = self._path(strategy_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
