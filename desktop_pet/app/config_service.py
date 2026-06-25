from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ConfigService:
    """安全读取应用配置中的点路径值。"""

    _MISSING = object()

    # 初始化当前对象及其依赖。
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self._config: Mapping[str, Any] = {} if config is None else config

    # 根据 config 更新update状态，并同步相关缓存或界面。
    def update(self, config: Mapping[str, Any] | None) -> None:
        """根据 config 更新update状态，并同步相关缓存或界面。"""
        self._config = {} if config is None else config

    # 根据 path、default 读取get并返回 Any。
    def get(self, path: str, default: Any = None) -> Any:
        """根据 path、default 读取get并返回 Any。"""
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

    # 读取配置项并转换为布尔值，缺失或无效时返回默认值。
    def get_bool(self, path: str, default: bool = False) -> bool:
        """读取配置项并转换为布尔值，缺失或无效时返回默认值。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return bool(value)

    # 读取配置项并转换为整数，缺失或无效时返回默认值。
    def get_int(self, path: str, default: int = 0) -> int:
        """读取配置项并转换为整数，缺失或无效时返回默认值。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # 读取配置项并转换为字符串，缺失或无效时返回默认值。
    def get_str(self, path: str, default: str = "") -> str:
        """读取配置项并转换为字符串，缺失或无效时返回默认值。"""
        value = self.get(path, self._MISSING)
        if value is self._MISSING or value is None:
            return default
        return str(value)
