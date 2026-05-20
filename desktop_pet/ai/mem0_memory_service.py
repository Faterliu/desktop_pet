from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


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

        try:
            from mem0 import Memory
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mem0 is enabled but mem0ai import failed: %s", exc)
            self.enabled = False
            return

        try:
            self._memory = Memory.from_config(self._mem0_config(memory_config))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialize Mem0 memory: %s", exc)
            self.enabled = False
            self._memory = None

    def is_available(self) -> bool:
        return self.enabled and self._memory is not None

    def _mem0_config(self, memory_config: dict[str, Any]) -> dict[str, Any]:
        """Build the Mem0 config while reusing this app's DeepSeek settings."""
        api_config = self.app_config.get("api", {})
        use_app_deepseek = bool(memory_config.get("mem0_use_app_deepseek_config", True))

        app_model = str(api_config.get("model", "")).strip()
        app_base_url = str(api_config.get("base_url", "")).strip()
        deepseek_api_key = str(api_config.get("api_key", "")).strip()

        deepseek_model = str(memory_config.get("mem0_deepseek_model", "")).strip()
        deepseek_base_url = str(memory_config.get("mem0_deepseek_base_url", "")).strip()
        if use_app_deepseek:
            deepseek_model = deepseek_model or app_model
            deepseek_base_url = deepseek_base_url or app_base_url

        config: dict[str, Any] = {
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
            }
        }

        embedder_provider = str(memory_config.get("mem0_embedder_provider", "default") or "default")
        if embedder_provider != "default":
            config["embedder"] = {"provider": embedder_provider}

        return config

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
            logger.warning("Failed to add Mem0 dialogue memory: %s", exc)

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
            logger.warning("Failed to add Mem0 text memory: %s", exc)

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
            results = self._memory.search(query=query, user_id=actual_user_id, limit=limit)
        except TypeError:
            try:
                results = self._memory.search(
                    query,
                    filters={"user_id": actual_user_id},
                    top_k=limit,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to search Mem0 memory: %s", exc)
                return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to search Mem0 memory: %s", exc)
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
