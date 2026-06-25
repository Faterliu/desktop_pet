from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger(__name__)


def _normalize_path(path: str | Path) -> Path:
    """规范化 `_normalize_path` 对应的数据。"""
    return Path(path)


def _backup_path(path: Path) -> Path:
    """处理 `_backup_path` 对应的业务逻辑。"""
    return path.with_name(f"{path.name}.bak")


def _tmp_path(path: Path) -> Path:
    """处理 `_tmp_path` 对应的业务逻辑。"""
    return path.with_name(f"{path.name}.tmp")


def _corrupt_path(path: Path) -> Path:
    """处理 `_corrupt_path` 对应的业务逻辑。"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    candidate = path.with_name(f"{path.name}.corrupt.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt.{timestamp}.{counter}")
        counter += 1
    return candidate


def _read_json_file(path: Path) -> Any:
    """读取 `_read_json_file` 所需的数据。"""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _move_corrupt_file(path: Path) -> Path | None:
    """处理 `_move_corrupt_file` 对应的业务逻辑。"""
    if not path.exists():
        return None

    corrupt = _corrupt_path(path)
    os.replace(path, corrupt)
    return corrupt


def cleanup_tmp_json_files(directory: Path) -> None:
    """处理 `cleanup_tmp_json_files` 对应的业务逻辑。"""
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


def ensure_json_file(path: str | Path, default: Any) -> Path:
    """处理 `ensure_json_file` 对应的业务逻辑。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        save_json(target, default)
    return target


def _restore_from_backup(target: Path, backup: Path) -> Any:
    """从可用备份恢复主 JSON 文件，并返回恢复后的内容。"""
    recovered = _read_json_file(backup)
    save_json(target, recovered)
    logger.warning("Restored JSON file %s from backup %s", target, backup)
    return recovered


def load_json(path: str | Path, default: Any = None) -> Any:
    """读取 `load_json` 所需的数据。"""
    target = _normalize_path(path)
    backup = _backup_path(target)
    if not target.exists() and backup.exists():
        try:
            return _restore_from_backup(target, backup)
        except json.JSONDecodeError as backup_exc:
            logger.error("JSON backup parse failed for %s: %s", backup, backup_exc)

    ensure_json_file(target, default if default is not None else {})

    try:
        return _read_json_file(target)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failed for %s: %s", target, exc)
        corrupt = _move_corrupt_file(target)
        if corrupt is not None:
            logger.warning("Moved corrupt JSON file from %s to %s", target, corrupt)

        if backup.exists():
            try:
                return _restore_from_backup(target, backup)
            except json.JSONDecodeError as backup_exc:
                logger.error("JSON backup parse failed for %s: %s", backup, backup_exc)

        logger.warning("Falling back to default content for %s", target)
        return copy.deepcopy(default)


def load_json_prefer_primary(
    primary_path: str | Path,
    fallback_path: str | Path,
    default: Any = None,
) -> Any:
    """读取 `load_json_prefer_primary` 所需的数据。"""
    primary = _normalize_path(primary_path)
    fallback = _normalize_path(fallback_path)

    if primary.exists():
        return load_json(primary, default)
    if fallback.exists():
        return load_json(fallback, default)
    return load_json(primary, default)


def save_json(path: str | Path, data: Any) -> Path:
    """保存 `save_json` 产生的数据。"""
    target = _normalize_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cleanup_tmp_json_files(target.parent)

    if target.exists() and target.stat().st_size > 0:
        shutil.copy2(target, _backup_path(target))

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
