from __future__ import annotations

from pathlib import Path
import threading


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


# 按规范化路径返回共享重入锁，避免同一 JSON 文件并发读改写。
def lock_for_path(path: str | Path) -> threading.RLock:
    """按规范化路径返回共享重入锁，避免同一 JSON 文件并发读改写。"""
    key = str(Path(path).resolve(strict=False))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock
