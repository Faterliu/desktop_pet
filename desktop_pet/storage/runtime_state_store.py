from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from utils.time_utils import parse_iso_datetime, utc_iso


_TIME_KEYS = (
    "last_user_interaction_at",
    "last_user_message_at",
    "last_proactive_shown_at",
    "last_proactive_replied_at",
)


class RuntimeStateStore:
    """保存少量跨重启仍有业务意义的运行状态。"""

    # 初始化运行状态存储路径。
    def __init__(self, path: str | Path) -> None:
        """初始化运行状态存储路径。"""
        self.path = Path(path)

    # 读取并校验时间字段，损坏或缺失字段使用空字符串。
    def load(self) -> dict[str, str]:
        """读取并校验时间字段，损坏或缺失字段使用空字符串。"""
        payload = load_json(self.path, {})
        if not isinstance(payload, dict):
            return {key: "" for key in _TIME_KEYS}
        return {
            key: utc_iso(parsed) if (parsed := parse_iso_datetime(payload.get(key))) else ""
            for key in _TIME_KEYS
        }

    # 保存经过校验的时间字段，避免其他运行态写入该文件。
    def save(self, state: dict[str, Any]) -> None:
        """保存经过校验的时间字段。"""
        payload = {
            key: utc_iso(parsed) if (parsed := parse_iso_datetime(state.get(key))) else ""
            for key in _TIME_KEYS
        }
        save_json(self.path, payload)
