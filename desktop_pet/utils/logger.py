from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONFIGURED = False
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5


class _RuntimeNoiseFilter(logging.Filter):
    """过滤已知的可选功能提示，保留同一模块中的真实故障。"""

    # 判断当前记录是否属于不需要写入运行日志的固定提示。
    def filter(self, record: logging.LogRecord) -> bool:
        """返回是否应继续写入当前处理器。"""
        message = record.getMessage()
        if record.name == "posthog":
            return not message.startswith("[PostHog] Multiple active PostHog clients detected")
        if record.name == "mem0.utils.spacy_models":
            return not message.startswith("Failed to load spaCy ")
        if record.name == "mem0.vector_stores.qdrant":
            return not message.startswith("fastembed not installed")
        return True


class _DashScopeEmbeddingSuccessFilter(logging.Filter):
    """将 DashScope Embedding 成功请求降为 DEBUG。"""

    # 仅降低成功响应的级别，不影响 httpx 的异常和其他请求。
    def filter(self, record: logging.LogRecord) -> bool:
        """按需修改成功请求的日志级别。"""
        message = record.getMessage()
        if (
            record.name == "httpx"
            and record.levelno == logging.INFO
            and message.startswith(
                "HTTP Request: POST https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings "
            )
            and '"HTTP/1.1 200' in message
        ):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


# 配置全局日志输出到控制台和 data/app.log。
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
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(_RuntimeNoiseFilter())
    root_logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RuntimeNoiseFilter())
    root_logger.addHandler(file_handler)

    httpx_logger = logging.getLogger("httpx")
    if not any(
        isinstance(log_filter, _DashScopeEmbeddingSuccessFilter)
        for log_filter in httpx_logger.filters
    ):
        httpx_logger.addFilter(_DashScopeEmbeddingSuccessFilter())

    _CONFIGURED = True


# 获取指定名称的日志记录器，并确保日志系统已初始化。
def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志记录器，并确保日志系统已初始化。"""
    configure_logging()
    return logging.getLogger(name)
