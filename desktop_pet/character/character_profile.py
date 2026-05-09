from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CharacterProfile:
    name: str = "小胡"
    role: str = "可爱温柔的桌面小伙伴"
    personality: list[str] = field(
        default_factory=lambda: ["可爱", "温柔", "安静陪伴", "不打扰用户", "喜欢鼓励用户"]
    )
