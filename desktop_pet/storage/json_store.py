from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger(__name__)


def _normalize_path(path: str | Path) -> Path:
    """把字符串或 Path 统一转换为 Path 对象。"""
    return Path(path)


def ensure_json_file(path: str | Path, default: Any) -> Path:
    """确保 JSON 文件存在；若不存在则写入默认内容。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        save_json(target, default)
    return target


def load_json(path: str | Path, default: Any = None) -> Any:
    """读取 JSON 文件；文件缺失时自动创建，损坏时回退到默认值。"""
    target = _normalize_path(path)
    ensure_json_file(target, default if default is not None else {})
    try:
        with target.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failed for %s: %s", target, exc)
        if default is not None:
            logger.warning("Falling back to default content for %s", target)
            return copy.deepcopy(default)
        raise ValueError(f"Invalid JSON content in {target}: {exc}") from exc


def load_json_prefer_primary(
    primary_path: str | Path,
    fallback_path: str | Path,
    default: Any = None,
) -> Any:
    """优先读取主文件；主文件缺失时回退到示例文件。"""
    primary = _normalize_path(primary_path)
    fallback = _normalize_path(fallback_path)

    if primary.exists():
        return load_json(primary, default)
    if fallback.exists():
        return load_json(fallback, default)
    return load_json(primary, default)


def save_json(path: str | Path, data: Any) -> Path:
    """把数据保存为 UTF-8 编码的 JSON 文件。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return target
