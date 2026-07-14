"""使用真实 app_config.json 探测 KLD AI Responses API 的独立脚本。

此文件不以 test_ 开头，避免 unittest discover 自动发起付费网络请求。
请在 desktop_pet 目录手动执行：
    ./.desktop_pet_venv/Scripts/python.exe -B tests/probe_kldai_responses.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from storage.json_store import load_json  # noqa: E402


# 从真实配置中读取 KLD AI Responses 所需的连接信息，不打印任何密钥。
def _kldai_config(config: dict[str, Any]) -> dict[str, Any]:
    """提取并校验真实配置中的 OpenAI/KLD AI 连接参数。"""
    api = config.get("api", {})
    openai = api.get("openai", {}) if isinstance(api, dict) else {}
    if not isinstance(openai, dict):
        openai = {}

    api_key = str(openai.get("api_key", "")).strip()
    if not api_key:
        api_key = os.getenv(str(openai.get("api_key_env", "OPENAI_API_KEY")), "").strip()
    return {
        "api_key": api_key,
        "base_url": str(openai.get("base_url", "")).rstrip("/"),
        "model": str(openai.get("model", "")).strip(),
        "timeout_seconds": openai.get("timeout_seconds", 30),
    }


# 从 Responses 响应中确认模型至少返回了可显示文本，而不输出回复正文。
def _has_output_text(data: Any) -> bool:
    """判断 Responses 响应是否包含非空文本。"""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return True
    output = data.get("output", [])
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                return True
    return False


# 发送一条最小化的真实 Responses 请求，仅验证认证、SSL 和基础模型响应。
def main() -> int:
    """执行 KLD AI Responses 实际连通性探测，并返回进程状态码。"""
    config_path = APP_ROOT / "config" / "app_config.json"
    config = load_json(config_path, {})
    if not isinstance(config, dict):
        print("探测失败：app_config.json 格式无效。")
        return 2

    api = _kldai_config(config)
    if api["base_url"].lower() != "https://www.kldai.cc":
        print("探测失败：当前 OpenAI base_url 不是 https://www.kldai.cc。")
        return 2
    if not api["api_key"] or not api["model"]:
        print("探测失败：KLD AI 的 API key 或模型未配置。")
        return 2

    payload = {
        "model": api["model"],
        "input": "请只回复 OK。",
        "max_output_tokens": 8,
    }
    headers = {
        "Authorization": f"Bearer {api['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            f"{api['base_url']}/responses",
            headers=headers,
            json=payload,
            timeout=api["timeout_seconds"],
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.SSLError:
        print("探测失败：KLD AI Responses SSL 连接中断。")
        return 1
    except requests.Timeout:
        print("探测失败：KLD AI Responses 请求超时。")
        return 1
    except requests.HTTPError:
        print(f"探测失败：KLD AI Responses 返回 HTTP {response.status_code}。")
        return 1
    except ValueError:
        print("探测失败：KLD AI Responses 返回的不是有效 JSON。")
        return 1
    except requests.RequestException:
        print("探测失败：无法连接 KLD AI Responses。")
        return 1

    if not _has_output_text(data):
        print("探测失败：KLD AI Responses 未返回可显示文字。")
        return 1
    print("探测成功：KLD AI Responses 已通过 SSL、认证和最小模型回复验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
