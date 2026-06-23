from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from character.emotion_state import EmotionState, parse_emotion_state


PERSONA_MODES = {"companion", "task", "emotional_support", "formal"}
ENERGY_LEVELS = {"low", "normal", "high"}


@dataclass(frozen=True, slots=True)
class PersonaState:
    """保存供后续人格调节使用的安全运行时状态。"""

    mood: EmotionState = EmotionState.CALM
    energy: str = "normal"
    closeness: float = 0.5
    mode: str = "companion"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PersonaState":
        """处理 `from_mapping` 对应的业务逻辑。"""
        source = value if isinstance(value, Mapping) else {}
        energy = _allowed_text(source.get("energy"), ENERGY_LEVELS, "normal")
        mode = _allowed_text(source.get("mode"), PERSONA_MODES, "companion")
        return cls(
            mood=parse_emotion_state(source.get("mood")),
            energy=energy,
            closeness=_closeness(source.get("closeness")),
            mode=mode,
        )

    def to_dict(self) -> dict[str, Any]:
        """处理 `to_dict` 对应的业务逻辑。"""
        result = asdict(self)
        result["mood"] = self.mood.value
        return result


def read_persona_state(value: Mapping[str, Any] | PersonaState | None = None) -> PersonaState:
    """读取 `read_persona_state` 所需的数据。"""
    if isinstance(value, PersonaState):
        return value
    return PersonaState.from_mapping(value)


def compact_behavior_policy(character: Mapping[str, Any] | None) -> dict[str, str]:
    """处理 `compact_behavior_policy` 对应的业务逻辑。"""
    if not isinstance(character, Mapping):
        return {}
    behavior = character.get("behavior_policy")
    scenarios = character.get("scenario_reactions")
    result: dict[str, str] = {}
    if isinstance(behavior, Mapping):
        for key in ("proactive_style", "memory_usage", "boundary"):
            text = _text(behavior.get(key), 160)
            if text:
                result[key] = text
    if isinstance(scenarios, Mapping):
        quiet_rule = _text(scenarios.get("user_silent_long_time"), 160)
        if quiet_rule:
            result["user_silent_long_time"] = quiet_rule
    return result


def _allowed_text(value: Any, allowed: set[str], default: str) -> str:
    """处理 `_allowed_text` 对应的业务逻辑。"""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _closeness(value: Any) -> float:
    """处理 `_closeness` 对应的业务逻辑。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(max(number, 0.0), 1.0)


def _text(value: Any, limit: int) -> str:
    """处理 `_text` 对应的业务逻辑。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
