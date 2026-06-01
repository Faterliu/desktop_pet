from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from storage.json_store import load_json_prefer_primary
from utils.logger import get_logger


logger = get_logger(__name__)


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, config_path: str | Path, fallback_config_path: str | Path | None = None) -> None:
        """初始化 DeepSeek 客户端，并绑定主配置和示例配置路径。"""
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path

    def _api_config(self) -> dict[str, Any]:
        """读取并返回 API 配置段。"""
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        return config.get("api", {})

    def is_configured(self) -> bool:
        """判断是否已经配置可用的 DeepSeek API Key。"""
        return bool(self._api_config().get("api_key", "").strip())

    def chat(self, messages: list[dict[str, str]]) -> str:
        """调用 DeepSeek 聊天接口并返回纯文本回复。"""
        api = self._api_config()
        api_key = api.get("api_key", "").strip()
        if not api_key:
            raise DeepSeekError("DeepSeek API key is empty.")

        base_url = api.get("base_url", "https://api.deepseek.com").rstrip("/")
        timeout_seconds = api.get("timeout_seconds", 30)
        payload = {
            "model": api.get("model", "deepseek-chat"),
            "messages": messages,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            logger.error("DeepSeek request timed out: %s", exc)
            raise DeepSeekError("我刚刚没来得及想好。") from exc
        except requests.RequestException as exc:
            logger.error("DeepSeek request failed: %s", exc)
            raise DeepSeekError("稍后再试试好不好。") from exc
        except ValueError as exc:
            logger.error("DeepSeek returned invalid JSON: %s", exc)
            raise DeepSeekError("我收到了一段看不懂的回复。") from exc

        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("DeepSeek response structure mismatch: %s", data)
            raise DeepSeekError("回复有点奇怪，我再缓一缓。") from exc

        if isinstance(message, list):
            parts = [part.get("text", "") for part in message if isinstance(part, dict)]
            return "".join(parts).strip()
        return str(message).strip()
