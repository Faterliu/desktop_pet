from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONFIGURED = False
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5


def configure_logging() -> None:
    """配置全局日志输出到控制台和 data/app.log。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir = PROJECT_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志记录器，并确保日志系统已初始化。"""
    configure_logging()
    return logging.getLogger(name)
