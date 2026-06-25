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

    # 初始化当前对象及其依赖。
    def __init__(self, local_lines_path: str | Path, metadata_path: str | Path | None = None) -> None:
        """初始化当前对象及其依赖。"""
        self.local_lines_path = Path(local_lines_path)
        self.metadata_path = Path(metadata_path) if metadata_path is not None else None

    # 读取本地台词 JSON 数据，并在缺失时返回默认结构。
    def payload(self) -> dict[str, Any]:
        """读取本地台词 JSON 数据，并在缺失时返回默认结构。"""
        payload = load_json(self.local_lines_path, {})
        return payload if isinstance(payload, dict) else {}

    # 读取指定台词组的台词列表，缺失时返回空列表。
    def get_lines(self, group: str) -> list[str]:
        """读取指定台词组的台词列表，缺失时返回空列表。"""
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

    # 从指定台词组中随机选择一条文本，缺失时返回兜底值。
    def pick_line(self, group: str, fallback: str = "") -> str:
        """从指定台词组中随机选择一条文本，缺失时返回兜底值。"""
        lines = self.get_lines(group)
        if not lines:
            return fallback
        return random.choice(lines)

    # 把人工台词加入指定分组，去重后写回本地台词文件。
    def append_manual_line(
        self,
        group: str,
        line: str,
        *,
        max_chars: int = 80,
    ) -> LocalLinesUpdateResult:
        """把人工台词加入指定分组，去重后写回本地台词文件。"""
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

    # 替换指定台词组的生成台词，并写入来源和刷新时间。
    def replace_generated_lines(
        self,
        group: str,
        lines: list[str],
        *,
        source: str,
        max_chars: int = 80,
        max_items: int = 10,
    ) -> LocalLinesUpdateResult:
        """替换指定台词组的生成台词，并写入来源和刷新时间。"""
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

    # 根据组配置、刷新间隔和上次更新时间判断是否需要刷新生成台词。
    def should_refresh_generated_lines(
        self,
        group: str,
        *,
        interval_days: int = 7,
        monthly_refresh: bool = True,
        now: datetime | None = None,
    ) -> bool:
        """根据组配置、刷新间隔和上次更新时间判断是否需要刷新生成台词。"""
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

    # 返回指定本地台词组的刷新来源、时间和统计信息。
    def group_metadata(self, group: str) -> dict[str, Any]:
        """返回指定本地台词组的刷新来源、时间和统计信息。"""
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

    # 过滤空白、过长或被禁用表达命中的台词文本。
    def validate_lines(self, lines: list[str], *, max_chars: int = 80) -> LocalLinesUpdateResult:
        """过滤空白、过长或被禁用表达命中的台词文本。"""
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

    # 读取首次启动台词后标记为已消费，避免下次重复展示。
    def consume_first_start_line(self) -> str:
        """读取首次启动台词后标记为已消费，避免下次重复展示。"""
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

    # 根据 payload、group 整理list group，并把结果交给调用方或写回状态。
    def _list_group(self, payload: dict[str, Any], group: str) -> list[str]:
        """根据 payload、group 整理list group，并把结果交给调用方或写回状态。"""
        value = payload.get(group, [])
        if isinstance(value, list):
            return [line.strip() for line in value if isinstance(line, str) and line.strip()]
        if isinstance(value, dict):
            lines = value.get("manual", value.get("data", []))
            if isinstance(lines, list):
                return [line.strip() for line in lines if isinstance(line, str) and line.strip()]
        return []

    # 根据 payload、group、lines 更新group台词状态，并同步相关缓存或界面。
    def _set_group_lines(self, payload: dict[str, Any], group: str, lines: list[str]) -> None:
        """根据 payload、group、lines 更新group台词状态，并同步相关缓存或界面。"""
        value = payload.get(group, [])
        if isinstance(value, dict) and "data" in value:
            payload[group] = {**value, "data": lines}
            return
        payload[group] = lines

    # 根据 group、lines、source 整理record generated metadata，并把结果交给调用方或写回状态。
    def _record_generated_metadata(self, group: str, lines: list[str], source: str) -> None:
        """根据 group、lines、source 整理record generated metadata，并把结果交给调用方或写回状态。"""
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


# 根据 lines 整理dedupe preserve order，并把结果交给调用方或写回状态。
def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    """根据 lines 整理dedupe preserve order，并把结果交给调用方或写回状态。"""
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


# 根据 line 整理contains blocked expression，并把结果交给调用方或写回状态。
def _contains_blocked_expression(line: str) -> bool:
    """根据 line 整理contains blocked expression，并把结果交给调用方或写回状态。"""
    lowered = line.lower()
    return any(blocked.lower() in lowered for blocked in BLOCKED_SUBSTRINGS)


# 解析 ISO 时间字符串，失败时返回 None。
def _parse_datetime(value: str) -> datetime | None:
    """解析 ISO 时间字符串，失败时返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
