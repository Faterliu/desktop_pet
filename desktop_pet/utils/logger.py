from __future__ import annotations

import logging
from pathlib import Path


_CONFIGURED = False


def configure_logging() -> None:
    """配置全局日志输出到控制台和 data/app.log。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    project_root = Path(__file__).resolve().parents[1]
    log_dir = project_root / "data"
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

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志记录器，并确保日志系统已初始化。"""
    configure_logging()
    return logging.getLogger(name)
