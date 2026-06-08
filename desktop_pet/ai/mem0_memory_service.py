from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from utils.log_sanitizer import safe_exception


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Mem0MemoryService:
    """Optional Mem0-backed long-term semantic memory service.

    The desktop pet must keep working when Mem0 is disabled, missing, or failing.
    All public methods degrade to no-op or empty results after logging.
    """

    def __init__(self, app_config: dict[str, Any]) -> None:
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

    def is_available(self) -> bool:
        return self.enabled and self._memory is not None

    def close(self) -> None:
        """Best-effort release for Mem0 local resources."""
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

    def _build_mem0_config(self, app_config: dict[str, Any]) -> dict[str, Any]:
        """Build Mem0 config with DeepSeek LLM and DashScope embeddings."""
        api_config = app_config.get("api", {})
        memory_config = app_config.get("memory", {})
        use_app_deepseek = bool(memory_config.get("mem0_use_app_deepseek_config", True))

        app_model = str(api_config.get("model", "")).strip()
        app_base_url = str(api_config.get("base_url", "")).strip()
        deepseek_api_key = str(api_config.get("api_key", "")).strip()

        deepseek_model = str(memory_config.get("mem0_deepseek_model", "")).strip()
        deepseek_base_url = str(memory_config.get("mem0_deepseek_base_url", "")).strip()
        if use_app_deepseek:
            deepseek_model = deepseek_model or app_model
            deepseek_base_url = deepseek_base_url or app_base_url

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

    def _mem0_config(self, memory_config: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible wrapper for older internal checks."""
        app_config = dict(self.app_config)
        app_config["memory"] = memory_config
        return self._build_mem0_config(app_config)

    def add_dialogue(
        self,
        user_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add one user-assistant dialogue to Mem0."""
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

    def add_memory_text(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add one already-extracted long-term memory text to Mem0."""
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

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search relevant memories for current user input."""
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

    def format_for_prompt(
        self,
        user_id: str,
        query: str,
        top_k: int | None = None,
    ) -> str:
        """Return bullet-list text suitable for PromptBuilder."""
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

    def has_any_memory(self, user_id: str) -> bool:
        """Best-effort check for knowledge-speak eligibility."""
        return bool(
            self.search(
                user_id=user_id,
                query="user preferences, goals, projects, learning plans, communication style",
                top_k=1,
            )
        )

    def _normalize_search_results(self, results: Any) -> list[dict[str, Any]]:
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

    def _positive_int(self, value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _float_value(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _dashscope_api_key(self, memory_config: dict[str, Any]) -> str:
        configured_key = str(memory_config.get("dashscope_api_key", "") or "").strip()
        if configured_key:
            return configured_key

        env_name = str(memory_config.get("dashscope_api_key_env", "DASHSCOPE_API_KEY") or "").strip()
        env_name = env_name or "DASHSCOPE_API_KEY"
        return str(os.getenv(env_name, "") or "").strip()

    def _has_required_embedding_config(self, memory_config: dict[str, Any]) -> bool:
        if self._dashscope_api_key(memory_config):
            return True

        logger.info(
            "Mem0 is enabled but no DashScope embedding key is configured; "
            "skipping Mem0 initialization."
        )
        return False

    def _is_sensitive_text(self, text: str) -> bool:
        """Simple local sensitive-memory guard."""
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
