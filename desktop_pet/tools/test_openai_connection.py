from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# 读取真实 app_config.json，并返回最小化的 OpenAI Responses 测试配置。
def _load_openai_test_config(config_path: Path) -> dict[str, Any]:
    """读取真实 app_config.json，并返回最小化的 OpenAI Responses 测试配置。"""
    if not config_path.exists():
        raise ValueError(f"未找到配置文件：{config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("app_config.json 无法读取或不是有效 JSON。") from exc
    if not isinstance(config, dict):
        raise ValueError("app_config.json 的根节点必须是对象。")

    api = config.get("api")
    if not isinstance(api, dict):
        raise ValueError("app_config.json 缺少 api 配置。")
    openai = api.get("openai")
    if not isinstance(openai, dict):
        raise ValueError("app_config.json 缺少 api.openai 配置。")

    base_url = str(openai.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        raise ValueError("api.openai.base_url 不能为空。")

    model = str(openai.get("model", "")).strip()
    if not model:
        raise ValueError("api.openai.model 不能为空。")

    wire_api = str(openai.get("wire_api", "")).strip().lower()
    if wire_api != "responses":
        raise ValueError("api.openai.wire_api 必须设置为 responses。")

    key = str(openai.get("api_key", "")).strip()
    if not key:
        key_env = str(openai.get("api_key_env", "OPENAI_API_KEY")).strip() or "OPENAI_API_KEY"
        key = os.getenv(key_env, "").strip()
    if not key:
        raise ValueError("OpenAI API key 未配置，请设置 api.openai.api_key 或对应环境变量。")

    timeout_seconds = openai.get("timeout_seconds", 30)
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise ValueError("api.openai.timeout_seconds 必须是数字。")
    if timeout_seconds <= 0:
        raise ValueError("api.openai.timeout_seconds 必须大于 0。")

    return {
        "base_url": base_url,
        "wire_api": "responses",
        "model": model,
        "api_key": key,
        "timeout_seconds": timeout_seconds,
    }


# 从 Responses API 的原始 JSON 返回体中提取助手文本。
def _response_text(data: Any) -> str:
    """从 Responses API 的原始 JSON 返回体中提取助手文本。"""
    if not isinstance(data, dict):
        return ""
    texts: list[str] = []
    output = data.get("output", [])
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "".join(texts)


# 按 app_config.json 中指定的 OpenAI 协议执行一次最小请求，并返回结果码。
def main() -> int:
    """按 app_config.json 中指定的 OpenAI 协议执行一次最小请求，并返回结果码。"""
    config_path = PROJECT_ROOT / "config" / "app_config.json"
    try:
        openai = _load_openai_test_config(config_path)
    except ValueError as exc:
        print(f"OpenAI 配置检查失败：{exc}")
        return 2

    model = str(openai["model"])
    endpoint = f"{str(openai['base_url']).rstrip('/')}/responses"
    print(f"模型：{model}")
    print(f"端点：{endpoint}")
    print("协议：responses")

    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {openai['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "instructions": "请简短、直接地回答。",
                "input": "请只回复：OpenAI 连接成功。",
            },
            timeout=float(openai["timeout_seconds"]),
        )
    except requests.Timeout:
        print("OpenAI 模型请求失败：请求超时。")
        return 1
    except requests.RequestException as exc:
        print(f"OpenAI 模型请求失败：{type(exc).__name__}。")
        return 1

    try:
        data = response.json()
    except ValueError:
        print(f"OpenAI 模型请求失败：HTTP {response.status_code}，返回体不是有效 JSON。")
        return 1

    if not response.ok:
        error = data.get("error") if isinstance(data, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if not message and isinstance(data, dict):
            message = data.get("message") or data.get("detail")
        detail = str(message).strip() if message else "服务端未提供错误详情。"
        print(f"OpenAI 模型请求失败：HTTP {response.status_code}，{detail}")
        return 1

    reply = _response_text(data)
    if not reply:
        print("OpenAI 模型请求失败：Responses API 返回成功，但没有可读取的 output_text。")
        return 1

    print("OpenAI 模型请求成功。")
    print(f"响应：{reply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
