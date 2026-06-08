from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from storage.json_store import load_json_prefer_primary
from utils.log_sanitizer import messages_shape, response_shape, safe_exception
from utils.logger import get_logger


logger = get_logger(__name__)


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, config_path: str | Path, fallback_config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path)
        self.fallback_config_path = Path(fallback_config_path) if fallback_config_path else self.config_path

    def _api_config(self) -> dict[str, Any]:
        config = load_json_prefer_primary(self.config_path, self.fallback_config_path, {})
        return config.get("api", {})

    def is_configured(self) -> bool:
        return bool(self._api_config().get("api_key", "").strip())

    def chat(self, messages: list[dict[str, str]]) -> str:
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
            logger.error(
                "DeepSeek request timed out: %s request=%s",
                safe_exception(exc),
                messages_shape(messages),
            )
            raise DeepSeekError("我刚刚没来得及想好。") from exc
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.error(
                "DeepSeek request failed: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise DeepSeekError("稍后再试试好不好。") from exc
        except ValueError as exc:
            status_code = getattr(response, "status_code", None) if "response" in locals() else None
            logger.error(
                "DeepSeek returned invalid JSON: %s status_code=%s request=%s",
                safe_exception(exc),
                status_code,
                messages_shape(messages),
            )
            raise DeepSeekError("我收到了一段看不懂的回复。") from exc

        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(
                "DeepSeek response structure mismatch: %s response=%s",
                safe_exception(exc),
                response_shape(data),
            )
            raise DeepSeekError("回复有点奇怪，我再缓一缓。") from exc

        if isinstance(message, list):
            parts = [part.get("text", "") for part in message if isinstance(part, dict)]
            return "".join(parts).strip()
        return str(message).strip()
