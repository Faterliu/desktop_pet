from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ConfigService:
    """安全读取应用配置中的点路径值。"""

    _MISSING = object()

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self._config: Mapping[str, Any] = {} if config is None else config

    def update(self, config: Mapping[str, Any] | None) -> None:
        """处理 `update` 对应的业务逻辑。"""
        self._config = {} if config is None else config

    def get(self, path: str, default: Any = None) -> Any:
        """处理 `get` 对应的业务逻辑。"""
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
        """读取 `get_bool` 所需的数据。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return bool(value)

    def get_int(self, path: str, default: int = 0) -> int:
        """读取 `get_int` 所需的数据。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_str(self, path: str, default: str = "") -> str:
        """读取 `get_str` 所需的数据。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return str(value)
