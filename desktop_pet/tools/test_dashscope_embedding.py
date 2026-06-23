from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    """读取 `_load_json` 所需的数据。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_app_config() -> dict[str, Any]:
    """读取 `_load_app_config` 所需的数据。"""
    primary = PROJECT_ROOT / "config" / "app_config.json"
    fallback = PROJECT_ROOT / "config" / "app_config.example.json"
    return _load_json(primary) or _load_json(fallback)


def _dashscope_api_key(memory_config: dict[str, Any]) -> str:
    """处理 `_dashscope_api_key` 对应的业务逻辑。"""
    configured_key = str(memory_config.get("dashscope_api_key", "") or "").strip()
    if configured_key:
        return configured_key

    env_name = str(memory_config.get("dashscope_api_key_env", "DASHSCOPE_API_KEY") or "").strip()
    env_name = env_name or "DASHSCOPE_API_KEY"
    return str(os.getenv(env_name, "") or "").strip()


def main() -> int:
    """运行当前模块的主流程。"""
    app_config = _load_app_config()
    memory_config = app_config.get("memory", {})

    api_key = _dashscope_api_key(memory_config)
    if not api_key:
        print("DashScope API key is missing. Set memory.dashscope_api_key or DASHSCOPE_API_KEY.")
        return 1

    base_url = str(
        memory_config.get(
            "dashscope_embedding_base_url",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    model = str(memory_config.get("dashscope_embedding_model", "text-embedding-v4") or "text-embedding-v4")
    dimensions = int(memory_config.get("dashscope_embedding_dimensions", 1024) or 1024)
    encoding_format = str(memory_config.get("dashscope_embedding_encoding_format", "float") or "float")

    response = requests.post(
        f"{base_url}/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": "测试 DashScope embedding 是否可用。",
            "dimensions": dimensions,
            "encoding_format": encoding_format,
        },
        timeout=30,
    )

    if response.status_code != 200:
        print("DashScope embedding failed")
        print("status:", response.status_code)
        print("body:", response.text)
        return 1

    result = response.json()
    data = result.get("data", [])
    if not data or not isinstance(data[0].get("embedding"), list):
        print("DashScope embedding response missing embedding vector.")
        return 1

    actual_dimensions = len(data[0]["embedding"])
    print("DashScope embedding ok")
    print("model:", model)
    print("dimensions:", actual_dimensions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
