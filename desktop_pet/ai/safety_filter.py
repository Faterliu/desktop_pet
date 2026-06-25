from __future__ import annotations


DISALLOWED_KEYWORDS = [
    "自杀",
    "炸弹",
    "迷奸",
    "色情",
]


# 检测消息中是否包含高风险关键词。
def contains_high_risk_request(message: str) -> bool:
    """检测消息中是否包含高风险关键词。"""
    lower_message = message.lower()
    return any(keyword.lower() in lower_message for keyword in DISALLOWED_KEYWORDS)
