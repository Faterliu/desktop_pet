from __future__ import annotations

from enum import Enum


class EmotionState(str, Enum):
    CALM = "calm"
    HAPPY = "happy"
    THINKING = "thinking"
    SLEEPY = "sleepy"
    SAD = "sad"
