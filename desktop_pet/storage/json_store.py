from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger(__name__)


# 把字符串或 Path 输入转换为展开用户目录后的 Path 对象。
def _normalize_path(path: str | Path) -> Path:
    """把字符串或 Path 输入转换为展开用户目录后的 Path 对象。"""
    return Path(path)


# 根据 path 生成 JSON 主文件对应的辅助文件路径。
def _tmp_path(path: Path) -> Path:
    """根据 path 生成 JSON 主文件对应的辅助文件路径。"""
    return path.with_name(f"{path.name}.tmp")


# 根据 path 生成 JSON 主文件对应的辅助文件路径。
def _corrupt_path(path: Path) -> Path:
    """根据 path 生成 JSON 主文件对应的辅助文件路径。"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    candidate = path.with_name(f"{path.name}.corrupt.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt.{timestamp}.{counter}")
        counter += 1
    return candidate


# 根据 path 读取JSON 文件并返回 Any。
def _read_json_file(path: Path) -> Any:
    """根据 path 读取JSON 文件并返回 Any。"""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


# 根据 path 处理文件路径或 JSON 内容，保持读写结果稳定。
def _move_corrupt_file(path: Path) -> Path | None:
    """根据 path 处理文件路径或 JSON 内容，保持读写结果稳定。"""
    if not path.exists():
        return None

    corrupt = _corrupt_path(path)
    os.replace(path, corrupt)
    return corrupt


# 根据 directory 清理临时文件JSONfiles线程注册和关联引用。
def cleanup_tmp_json_files(directory: Path) -> None:
    """根据 directory 清理临时文件JSONfiles线程注册和关联引用。"""
    target_dir = _normalize_path(directory)
    if not target_dir.exists() or not target_dir.is_dir():
        return

    for tmp_file in target_dir.glob("*.tmp"):
        if not tmp_file.is_file():
            continue
        try:
            tmp_file.unlink()
        except OSError as exc:
            logger.warning("Failed to remove temporary JSON file %s: %s", tmp_file, exc)


# 根据 path、default 处理文件路径或 JSON 内容，保持读写结果稳定。
def ensure_json_file(path: str | Path, default: Any) -> Path:
    """根据 path、default 处理文件路径或 JSON 内容，保持读写结果稳定。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        save_json(target, default)
    return target


# 根据 path、default 读取JSON并返回 Any。
def load_json(path: str | Path, default: Any = None) -> Any:
    """根据 path、default 读取JSON并返回 Any。"""
    target = _normalize_path(path)
    ensure_json_file(target, default if default is not None else {})

    try:
        return _read_json_file(target)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failed for %s: %s", target, exc)
        corrupt = _move_corrupt_file(target)
        if corrupt is not None:
            logger.warning("Moved corrupt JSON file from %s to %s", target, corrupt)

        logger.warning("Falling back to default content for %s", target)
        return copy.deepcopy(default)


# 根据 primary_path、fallback_path、default 读取JSON prefer primary并返回 Any。
def load_json_prefer_primary(
    primary_path: str | Path,
    fallback_path: str | Path,
    default: Any = None,
) -> Any:
    """根据 primary_path、fallback_path、default 读取JSON prefer primary并返回 Any。"""
    primary = _normalize_path(primary_path)
    fallback = _normalize_path(fallback_path)

    if primary.exists():
        return load_json(primary, default)
    if fallback.exists():
        return load_json(fallback, default)
    return load_json(primary, default)


# 根据 path、data 把JSON写入持久化存储并保持数据可恢复。
def save_json(path: str | Path, data: Any) -> Path:
    """根据 path、data 把JSON写入持久化存储并保持数据可恢复。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cleanup_tmp_json_files(target.parent)

    tmp = _tmp_path(target)
    try:
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError as exc:
            logger.warning("Failed to remove temporary JSON file %s: %s", tmp, exc)
        raise

    return target
