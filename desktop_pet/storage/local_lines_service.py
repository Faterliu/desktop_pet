from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from storage.json_store import load_json, save_json


BLOCKED_SUBSTRINGS = (
    "memory.json",
    "mem0",
    "数据库",
    "数据存储器",
    "根据记忆",
    "根据你的记忆",
    "你之前说过",
)


@dataclass(frozen=True)
class LocalLinesUpdateResult:
    """记录本地台词受控更新的结果摘要。"""

    group: str
    accepted: list[str]
    rejected: list[str]
    saved: bool


class LocalLinesService:
    """在不改变文件结构的前提下安全读写本地台词。"""

    def __init__(self, local_lines_path: str | Path, metadata_path: str | Path | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self.local_lines_path = Path(local_lines_path)
        self.metadata_path = Path(metadata_path) if metadata_path is not None else None

    def payload(self) -> dict[str, Any]:
        """处理 `payload` 对应的业务逻辑。"""
        payload = load_json(self.local_lines_path, {})
        return payload if isinstance(payload, dict) else {}

    def get_lines(self, group: str) -> list[str]:
        """读取 `get_lines` 所需的数据。"""
        value = self.payload().get(group, [])
        if isinstance(value, list):
            return [line.strip() for line in value if isinstance(line, str) and line.strip()]
        if isinstance(value, dict):
            merged: list[str] = []
            for key in ("manual", "generated", "data"):
                lines = value.get(key, [])
                if isinstance(lines, list):
                    merged.extend(line.strip() for line in lines if isinstance(line, str) and line.strip())
            return _dedupe_preserve_order(merged)
        return []

    def pick_line(self, group: str, fallback: str = "") -> str:
        """选择 `pick_line` 对应的内容。"""
        lines = self.get_lines(group)
        if not lines:
            return fallback
        return random.choice(lines)

    def append_manual_line(
        self,
        group: str,
        line: str,
        *,
        max_chars: int = 80,
    ) -> LocalLinesUpdateResult:
        """添加 `append_manual_line` 对应的内容。"""
        result = self.validate_lines([line], max_chars=max_chars)
        if not result.accepted:
            return LocalLinesUpdateResult(group, [], result.rejected, False)

        payload = self.payload()
        current = self._list_group(payload, group)
        merged = _dedupe_preserve_order([*current, *result.accepted])
        if merged == current:
            return LocalLinesUpdateResult(group, result.accepted, result.rejected, False)

        payload[group] = merged
        save_json(self.local_lines_path, payload)
        return LocalLinesUpdateResult(group, result.accepted, result.rejected, True)

    def replace_generated_lines(
        self,
        group: str,
        lines: list[str],
        *,
        source: str,
        max_chars: int = 80,
        max_items: int = 10,
    ) -> LocalLinesUpdateResult:
        """处理 `replace_generated_lines` 对应的业务逻辑。"""
        validation = self.validate_lines(lines, max_chars=max_chars)
        accepted = validation.accepted[: max(max_items, 0)]
        if not accepted:
            return LocalLinesUpdateResult(group, [], validation.rejected, False)

        payload = self.payload()
        manual = self._list_group(payload, group)
        merged = _dedupe_preserve_order([*manual, *accepted])
        self._set_group_lines(payload, group, merged)
        save_json(self.local_lines_path, payload)
        self._record_generated_metadata(group, accepted, source)
        return LocalLinesUpdateResult(group, accepted, validation.rejected, True)

    def should_refresh_generated_lines(
        self,
        group: str,
        *,
        interval_days: int = 7,
        monthly_refresh: bool = True,
        now: datetime | None = None,
    ) -> bool:
        """判断 `should_refresh_generated_lines` 对应的条件是否成立。"""
        metadata = self.group_metadata(group)
        if not metadata:
            return True

        current = now or datetime.now()
        if monthly_refresh and metadata.get("last_monthly_refresh") != current.strftime("%Y-%m"):
            return True

        last_refreshed = _parse_datetime(str(metadata.get("last_refreshed_at", "")))
        if last_refreshed is None:
            return True

        try:
            days = int(interval_days)
        except (TypeError, ValueError):
            days = 7
        if days <= 0:
            return True
        return current - last_refreshed >= timedelta(days=days)

    def group_metadata(self, group: str) -> dict[str, Any]:
        """处理 `group_metadata` 对应的业务逻辑。"""
        if self.metadata_path is None:
            return {}
        metadata = load_json(self.metadata_path, {})
        if not isinstance(metadata, dict):
            return {}
        groups = metadata.get("groups", {})
        if not isinstance(groups, dict):
            return {}
        group_metadata = groups.get(group, {})
        return group_metadata if isinstance(group_metadata, dict) else {}

    def validate_lines(self, lines: list[str], *, max_chars: int = 80) -> LocalLinesUpdateResult:
        """校验 `validate_lines` 对应的数据或状态。"""
        accepted: list[str] = []
        rejected: list[str] = []
        seen: set[str] = set()
        limit = max(max_chars, 1)

        for raw_line in lines:
            line = raw_line.strip() if isinstance(raw_line, str) else ""
            if not line:
                rejected.append(str(raw_line))
                continue
            if len(line) > limit or _contains_blocked_expression(line):
                rejected.append(line)
                continue
            if line in seen:
                rejected.append(line)
                continue
            seen.add(line)
            accepted.append(line)

        return LocalLinesUpdateResult("", accepted, rejected, False)

    def consume_first_start_line(self) -> str:
        """处理 `consume_first_start_line` 对应的业务逻辑。"""
        payload = self.payload()
        first_start = payload.get("first_start", {})
        if not isinstance(first_start, dict) or not first_start.get("enable", False):
            return ""

        lines = first_start.get("data", [])
        if not isinstance(lines, list):
            return ""
        candidates = [line.strip() for line in lines if isinstance(line, str) and line.strip()]
        if not candidates:
            return ""

        line = random.choice(candidates)
        first_start["enable"] = False
        payload["first_start"] = first_start
        save_json(self.local_lines_path, payload)
        return line

    def _list_group(self, payload: dict[str, Any], group: str) -> list[str]:
        """处理 `_list_group` 对应的业务逻辑。"""
        value = payload.get(group, [])
        if isinstance(value, list):
            return [line.strip() for line in value if isinstance(line, str) and line.strip()]
        if isinstance(value, dict):
            lines = value.get("manual", value.get("data", []))
            if isinstance(lines, list):
                return [line.strip() for line in lines if isinstance(line, str) and line.strip()]
        return []

    def _set_group_lines(self, payload: dict[str, Any], group: str, lines: list[str]) -> None:
        """更新 `_set_group_lines` 对应的状态。"""
        value = payload.get(group, [])
        if isinstance(value, dict) and "data" in value:
            payload[group] = {**value, "data": lines}
            return
        payload[group] = lines

    def _record_generated_metadata(self, group: str, lines: list[str], source: str) -> None:
        """处理 `_record_generated_metadata` 对应的业务逻辑。"""
        if self.metadata_path is None:
            return

        metadata = load_json(self.metadata_path, {})
        if not isinstance(metadata, dict):
            metadata = {}
        groups = metadata.setdefault("groups", {})
        now = datetime.now()
        previous = groups.get(group, {})
        if not isinstance(previous, dict):
            previous = {}
        groups[group] = {
            **previous,
            "source": source,
            "updated_at": now.isoformat(timespec="seconds"),
            "last_refreshed_at": now.isoformat(timespec="seconds"),
            "last_monthly_refresh": now.strftime("%Y-%m"),
            "count": len(lines),
            "lines": lines,
        }
        save_json(self.metadata_path, metadata)


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    """处理 `_dedupe_preserve_order` 对应的业务逻辑。"""
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def _contains_blocked_expression(line: str) -> bool:
    """处理 `_contains_blocked_expression` 对应的业务逻辑。"""
    lowered = line.lower()
    return any(blocked.lower() in lowered for blocked in BLOCKED_SUBSTRINGS)


def _parse_datetime(value: str) -> datetime | None:
    """解析 `_parse_datetime` 对应的数据。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
