from __future__ import annotations

from datetime import datetime


def now_local() -> datetime:
    """返回当前本地时间对象。"""
    return datetime.now()


def now_iso() -> str:
    """返回精确到秒的本地 ISO 时间字符串。"""
    return now_local().isoformat(timespec="seconds")


def today_str() -> str:
    """返回当前日期字符串，格式为 YYYY-MM-DD。"""
    return now_local().date().isoformat()
