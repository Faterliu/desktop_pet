from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ConfigService:
    """Small helper for safe dotted-path reads from app config dictionaries."""

    _MISSING = object()

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config: Mapping[str, Any] = {} if config is None else config

    def update(self, config: Mapping[str, Any] | None) -> None:
        """Point the service at a freshly loaded config dictionary."""
        self._config = {} if config is None else config

    def get(self, path: str, default: Any = None) -> Any:
        """Return a dotted config path, or default when any node is missing."""
        if not path:
            return default

        current: Any = self._config
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return default
            current = current.get(part, self._MISSING)
            if current is self._MISSING:
                return default
        return current

    def get_bool(self, path: str, default: bool = False) -> bool:
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return bool(value)

    def get_int(self, path: str, default: int = 0) -> int:
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_str(self, path: str, default: str = "") -> str:
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return str(value)
