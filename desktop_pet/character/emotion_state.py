from __future__ import annotations

from enum import Enum


class EmotionState(str, Enum):
    CALM = "calm"
    HAPPY = "happy"
    THINKING = "thinking"
    SLEEPY = "sleepy"
    SAD = "sad"


# 把配置中的情绪字符串解析为 EmotionState，缺失时返回默认情绪。
def parse_emotion_state(value: object, default: EmotionState = EmotionState.CALM) -> EmotionState:
    """把配置中的情绪字符串解析为 EmotionState，缺失时返回默认情绪。"""
    if isinstance(value, EmotionState):
        return value
    try:
        return EmotionState(str(value).strip().lower())
    except (TypeError, ValueError):
        return default
