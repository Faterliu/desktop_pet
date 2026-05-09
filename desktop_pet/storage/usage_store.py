from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json
from utils.time_utils import today_str


DEFAULT_DAILY_USAGE = {
    "date": "",
    "local_proactive_lines_used": 0,
    "api_proactive_lines_used": 0,
    "morning_greeting_used": False,
    "afternoon_greeting_used": False,
    "evening_greeting_used": False,
}


class UsageStore:
    def __init__(self, path: str | Path) -> None:
        """初始化每日用量存储，并绑定目标 JSON 文件路径。"""
        self.path = Path(path)

    def _ensure_today(self) -> dict[str, Any]:
        """确保统计数据属于今天；跨天时自动重置计数。"""
        payload = load_json(self.path, DEFAULT_DAILY_USAGE)
        today = today_str()
        if payload.get("date") != today:
            payload = dict(DEFAULT_DAILY_USAGE)
            payload["date"] = today
            save_json(self.path, payload)
        return payload

    def get_usage(self) -> dict[str, Any]:
        """返回今天的用量统计。"""
        return self._ensure_today()

    def can_use_local(self, max_per_day: int) -> bool:
        """判断今天是否还能继续使用本地主动话术。"""
        return self._ensure_today().get("local_proactive_lines_used", 0) < max_per_day

    def can_use_api(self, max_per_day: int) -> bool:
        """判断今天是否还能继续使用 API 主动回复额度。"""
        return self._ensure_today().get("api_proactive_lines_used", 0) < max_per_day

    def increment_local_line(self) -> dict[str, Any]:
        """本地主动话术计数加一，并返回最新统计。"""
        payload = self._ensure_today()
        payload["local_proactive_lines_used"] = payload.get("local_proactive_lines_used", 0) + 1
        save_json(self.path, payload)
        return payload

    def increment_api_line(self) -> dict[str, Any]:
        """API 主动回复计数加一，并返回最新统计。"""
        payload = self._ensure_today()
        payload["api_proactive_lines_used"] = payload.get("api_proactive_lines_used", 0) + 1
        save_json(self.path, payload)
        return payload
