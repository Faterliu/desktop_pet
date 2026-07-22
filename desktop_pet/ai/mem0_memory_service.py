from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from utils.log_sanitizer import safe_exception


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Mem0MemoryService:
    """提供可选的 Mem0 长期语义记忆服务。"""

    # 初始化当前对象及其依赖。
    def __init__(self, app_config: dict[str, Any]) -> None:
        """初始化当前对象及其依赖。"""
        self.app_config = app_config
        memory_config = app_config.get("memory", {})

        self.enabled = bool(memory_config.get("enable_mem0", False))
        self.top_k = self._positive_int(memory_config.get("mem0_search_top_k", 5), 5)
        self.default_user_id = str(memory_config.get("mem0_user_id", "default_user"))
        self.write_sensitive_memory = bool(memory_config.get("write_sensitive_memory", False))
        self._memory: Any | None = None

        if not self.enabled:
            return

        if not self._has_required_embedding_config(memory_config):
            self.enabled = False
            return

        try:
            from mem0 import Memory
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mem0 is enabled but mem0ai import failed: %s", safe_exception(exc))
            self.enabled = False
            return

        try:
            self._memory = Memory.from_config(self._build_mem0_config(app_config))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialize Mem0 memory: %s", safe_exception(exc))
            self.enabled = False
            self._memory = None

    # 判断available是否满足条件并返回布尔结果。
    def is_available(self) -> bool:
        """判断available是否满足条件并返回布尔结果。"""
        return self.enabled and self._memory is not None

    # 停止Mem0MemoryService持有的资源并释放后台状态。
    def close(self) -> None:
        """停止Mem0MemoryService持有的资源并释放后台状态。"""
        if self._memory is None:
            return

        try:
            close = getattr(self._memory, "close", None)
            if callable(close):
                close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close Mem0 memory: %s", safe_exception(exc))
        finally:
            self._memory = None
            self.enabled = False

    # 根据 app_config 读取配置片段，缺失时返回安全默认配置。
    def _build_mem0_config(self, app_config: dict[str, Any]) -> dict[str, Any]:
        """根据 app_config 读取配置片段，缺失时返回安全默认配置。"""
        api_config = app_config.get("api", {})
        memory_config = app_config.get("memory", {})
        api_config = api_config if isinstance(api_config, dict) else {}
        deepseek_config = api_config.get("deepseek", {})
        deepseek_config = deepseek_config if isinstance(deepseek_config, dict) else {}
        use_app_deepseek = bool(memory_config.get("mem0_use_app_deepseek_config", True))

        deepseek_api_key = str(deepseek_config.get("api_key", "")).strip()
        deepseek_model = str(memory_config.get("mem0_deepseek_model", "")).strip()
        deepseek_base_url = str(memory_config.get("mem0_deepseek_base_url", "")).strip()
        if use_app_deepseek:
            deepseek_model = deepseek_model or str(deepseek_config.get("model", "")).strip()
            deepseek_base_url = deepseek_base_url or str(deepseek_config.get("base_url", "")).strip()

        deepseek_model = deepseek_model or "deepseek-chat"
        deepseek_base_url = deepseek_base_url or "https://api.deepseek.com"

        dashscope_api_key = self._dashscope_api_key(memory_config)
        if not dashscope_api_key:
            raise ValueError(
                "DashScope API key is missing. Set memory.dashscope_api_key "
                "or the DASHSCOPE_API_KEY environment variable."
            )

        embedding_dims = self._positive_int(
            memory_config.get("dashscope_embedding_dimensions", 1024),
            1024,
        )
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        qdrant_path = PROJECT_ROOT / "data" / "mem0_qdrant"
        qdrant_path.mkdir(parents=True, exist_ok=True)

        config: dict[str, Any] = {
            "history_db_path": str(data_dir / "mem0_history.db"),
            "llm": {
                "provider": "deepseek",
                "config": {
                    "model": deepseek_model,
                    "deepseek_base_url": deepseek_base_url,
                    "api_key": deepseek_api_key,
                    "temperature": self._float_value(memory_config.get("mem0_temperature", 0.2), 0.2),
                    "max_tokens": self._positive_int(
                        memory_config.get("mem0_max_tokens", 2000),
                        2000,
                    ),
                    "top_p": self._float_value(memory_config.get("mem0_top_p", 1.0), 1.0),
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": str(
                        memory_config.get("dashscope_embedding_model", "text-embedding-v4")
                    ).strip()
                    or "text-embedding-v4",
                    "api_key": dashscope_api_key,
                    "openai_base_url": str(
                        memory_config.get(
                            "dashscope_embedding_base_url",
                            "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        )
                    ).strip()
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "embedding_dims": embedding_dims,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": str(
                        memory_config.get("mem0_qdrant_collection", "desktop_pet_mem0")
                    ).strip()
                    or "desktop_pet_mem0",
                    "embedding_model_dims": embedding_dims,
                    "path": str(qdrant_path),
                    "on_disk": True,
                },
            },
        }

        return config

    # 根据 memory_config 读取配置片段，缺失时返回安全默认配置。
    def _mem0_config(self, memory_config: dict[str, Any]) -> dict[str, Any]:
        """根据 memory_config 读取配置片段，缺失时返回安全默认配置。"""
        app_config = dict(self.app_config)
        app_config["memory"] = memory_config
        return self._build_mem0_config(app_config)

    # 根据 user_id、user_message、assistant_message 把对话加入当前状态或持久化记录。
    def add_dialogue(
        self,
        user_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """根据 user_id、user_message、assistant_message 把对话加入当前状态或持久化记录。"""
        if not self.is_available():
            return

        user_message = (user_message or "").strip()
        assistant_message = (assistant_message or "").strip()
        if not user_message:
            return

        if self._is_sensitive_text(user_message) and not self.write_sensitive_memory:
            logger.info("Skip sensitive Mem0 dialogue memory.")
            return

        messages = [{"role": "user", "content": user_message}]
        if assistant_message:
            messages.append({"role": "assistant", "content": assistant_message})

        try:
            self._memory.add(
                messages,
                user_id=user_id or self.default_user_id,
                metadata=metadata or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to add Mem0 dialogue memory: %s", safe_exception(exc))

    # 根据 user_id、text、metadata 把记忆 文本加入当前状态或持久化记录。
    def add_memory_text(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """根据 user_id、text、metadata 把记忆 文本加入当前状态或持久化记录。"""
        if not self.is_available():
            return

        text = (text or "").strip()
        if not text:
            return

        if self._is_sensitive_text(text) and not self.write_sensitive_memory:
            logger.info("Skip sensitive Mem0 text memory.")
            return

        try:
            self._memory.add(
                [{"role": "user", "content": text}],
                user_id=user_id or self.default_user_id,
                metadata=metadata or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to add Mem0 text memory: %s", safe_exception(exc))

    # 根据 user_id、query、top_k 整理search，并把结果交给调用方或写回状态。
    def search(
        self,
        user_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """根据 user_id、query、top_k 整理search，并把结果交给调用方或写回状态。"""
        if not self.is_available():
            return []

        query = (query or "").strip()
        if not query:
            return []

        limit = self._positive_int(top_k, self.top_k)
        actual_user_id = user_id or self.default_user_id
        try:
            results = self._memory.search(
                query=query,
                filters={"user_id": actual_user_id},
                top_k=limit,
            )
        except TypeError:
            try:
                results = self._memory.search(query=query, user_id=actual_user_id, limit=limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to search Mem0 memory: %s", safe_exception(exc))
                return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to search Mem0 memory: %s", safe_exception(exc))
            return []

        return self._normalize_search_results(results)

    # 根据 user_id、query、top_k 整理format for 提示词，并把结果交给调用方或写回状态。
    def format_for_prompt(
        self,
        user_id: str,
        query: str,
        top_k: int | None = None,
    ) -> str:
        """根据 user_id、query、top_k 整理format for 提示词，并把结果交给调用方或写回状态。"""
        lines: list[str] = []
        seen: set[str] = set()
        for item in self.search(user_id=user_id, query=query, top_k=top_k):
            text = (
                item.get("memory")
                or item.get("text")
                or item.get("content")
                or item.get("value")
                or ""
            )
            text = str(text).strip()
            if text and text not in seen:
                seen.add(text)
                lines.append(f"- {text}")
        return "\n".join(lines)

    # 根据 user_id 判断any记忆是否满足条件并返回布尔结果。
    def has_any_memory(self, user_id: str) -> bool:
        """根据 user_id 判断any记忆是否满足条件并返回布尔结果。"""
        return bool(
            self.search(
                user_id=user_id,
                query="user preferences, goals, projects, learning plans, communication style",
                top_k=1,
            )
        )

    # 把 Mem0 检索返回值整理为统一的字典列表。
    def _normalize_search_results(self, results: Any) -> list[dict[str, Any]]:
        """把 Mem0 检索返回值整理为统一的字典列表。"""
        if isinstance(results, dict):
            raw_items = results.get("results") or results.get("memories") or []
        else:
            raw_items = results or []

        normalized: list[dict[str, Any]] = []
        if not isinstance(raw_items, list):
            return normalized

        for item in raw_items:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append({"memory": item})
        return normalized

    # 根据 value、default 转换为正整数，失败或小于等于零时返回默认值。
    def _positive_int(self, value: Any, default: int) -> int:
        """根据 value、default 转换为正整数，失败或小于等于零时返回默认值。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    # 根据 value、default 转换为浮点数，失败时返回默认值。
    def _float_value(self, value: Any, default: float) -> float:
        """根据 value、default 转换为浮点数，失败时返回默认值。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # 根据 memory_config 从环境变量或配置中读取 DashScope API 密钥。
    def _dashscope_api_key(self, memory_config: dict[str, Any]) -> str:
        """根据 memory_config 从环境变量或配置中读取 DashScope API 密钥。"""
        configured_key = str(memory_config.get("dashscope_api_key", "") or "").strip()
        if configured_key:
            return configured_key

        env_name = str(memory_config.get("dashscope_api_key_env", "DASHSCOPE_API_KEY") or "").strip()
        env_name = env_name or "DASHSCOPE_API_KEY"
        return str(os.getenv(env_name, "") or "").strip()

    # 根据 memory_config 读取配置片段，缺失时返回安全默认配置。
    def _has_required_embedding_config(self, memory_config: dict[str, Any]) -> bool:
        """根据 memory_config 读取配置片段，缺失时返回安全默认配置。"""
        if self._dashscope_api_key(memory_config):
            return True

        logger.info(
            "Mem0 is enabled but no DashScope embedding key is configured; "
            "skipping Mem0 initialization."
        )
        return False

    # 根据 text 判断sensitive文本是否满足条件并返回布尔结果。
    def _is_sensitive_text(self, text: str) -> bool:
        """根据 text 判断sensitive文本是否满足条件并返回布尔结果。"""
        sensitive_keywords = [
            "自杀",
            "自残",
            "轻生",
            "抑郁",
            "诊断",
            "药物",
            "病历",
            "身份证",
            "住址",
            "银行卡",
            "密码",
            "债务",
            "家庭暴力",
            "创伤",
        ]
        return any(keyword in (text or "") for keyword in sensitive_keywords)
