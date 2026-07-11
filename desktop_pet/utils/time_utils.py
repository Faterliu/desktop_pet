from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


# 返回当前本地时间对象。
def now_local() -> datetime:
    """返回当前本地时间对象。"""
    return datetime.now()


# 返回带时区的当前 UTC 时间，供需要持久化的业务状态使用。
def now_utc() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


# 将时间转换为带时区的 UTC 时间；旧版无时区值按本机时区解释。
def to_utc(value: datetime) -> datetime:
    """将时间转换为带时区的 UTC 时间。"""
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc)


# 生成可持久化的带时区 ISO 8601 时间字符串。
def utc_iso(value: datetime | None = None) -> str:
    """生成可持久化的带时区 ISO 8601 时间字符串。"""
    return to_utc(value or now_utc()).isoformat(timespec="seconds")


# 安全解析带时区 ISO 8601 时间；无效值返回 None，旧版无时区值兼容为本机时区。
def parse_iso_datetime(value: Any) -> datetime | None:
    """安全解析带时区 ISO 8601 时间。"""
    if isinstance(value, datetime):
        return to_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_utc(parsed)


# 优先用单调时钟计算运行期时长，跨重启或缺少单调基准时回退 UTC 墙钟。
def elapsed_seconds(
    since: datetime | None,
    monotonic_since: float | None = None,
) -> float:
    """优先用单调时钟计算运行期时长。"""
    if monotonic_since is not None:
        return max(0.0, time.monotonic() - monotonic_since)
    if since is None:
        return float("inf")
    return max(0.0, (now_utc() - to_utc(since)).total_seconds())


# 返回精确到秒的本地 ISO 时间字符串。
def now_iso() -> str:
    """返回精确到秒的本地 ISO 时间字符串。"""
    return now_local().isoformat(timespec="seconds")


# 返回当前日期字符串，格式为 YYYY-MM-DD。
def today_str() -> str:
    """返回当前日期字符串，格式为 YYYY-MM-DD。"""
    return now_local().date().isoformat()
