from __future__ import annotations

from enum import Enum


class EmotionState(str, Enum):
    CALM = "calm"
    HAPPY = "happy"
    THINKING = "thinking"
    SLEEPY = "sleepy"
    SAD = "sad"


def parse_emotion_state(value: object, default: EmotionState = EmotionState.CALM) -> EmotionState:
    """解析 `parse_emotion_state` 对应的数据。"""
    if isinstance(value, EmotionState):
        return value
    try:
        return EmotionState(str(value).strip().lower())
    except (TypeError, ValueError):
        return default
