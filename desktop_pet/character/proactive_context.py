from __future__ import annotations

import random
from typing import Any

from storage.memory_store import normalize_memory_schema


FORBIDDEN_GREETING_PHRASES = (
    "根据记忆",
    "你之前说过",
    "我读取到",
    "memory.json",
    "Mem0",
    "数据库",
    "配置项",
)


def build_proactive_context(
    memory: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
    time_period: str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    """Build a compact context for scenario greetings from memory and runtime state."""
    normalized = normalize_memory_schema(memory)
    work_study = normalized.get("work_study", {})
    relationship = normalized.get("relationship_memory", {})
    communication = relationship.get("communication_style", {})
    companionship = relationship.get("companionship_style", {})
    interaction = relationship.get("interaction_patterns", {})

    task_focus = _unique_limited(
        _string_items(interaction.get("task_focus", []))
        + _string_items(work_study.get("current_projects", []))
        + _string_items(work_study.get("current_learning_topics", [])),
        limit=4,
    )

    return {
        "time_period": time_period or "",
        "season": season or "",
        "recent_task_focus": task_focus,
        "communication_style": _compact_mapping(
            communication,
            [
                "preferred_response_style",
                "detail_level",
                "confirmation_preference",
                "tone_preference",
            ],
        ),
        "companionship_style": _compact_mapping(
            companionship,
            [
                "preferred_companion_role",
                "proactive_boundary",
                "encouragement_style",
                "avoid_behaviors",
            ],
        ),
        "interaction_patterns": _compact_mapping(
            interaction,
            [
                "recent_interaction_mode",
                "interruption_tolerance",
                "response_to_proactive_greetings",
            ],
        ),
        "runtime_state": dict(runtime_state or {}),
    }


def has_scenario_context(context: dict[str, Any], min_items: int = 1) -> bool:
    """Return whether the compact context has enough useful memory to personalize a line."""
    return _count_context_items(context) >= max(1, min_items)


def build_local_scenario_greeting(
    context: dict[str, Any],
    local_lines: dict[str, Any],
    max_chars: int = 80,
    greeting_type: str = "memory_context_greeting",
) -> str:
    """Render a local fallback scenario greeting from compact context and templates."""
    if greeting_type == "low_interrupt_greeting":
        return sanitize_scenario_greeting(_pick_line(local_lines, "low_interrupt"), max_chars)

    task = _primary_task(context)
    if not task:
        return ""
    templates = _string_items(local_lines.get("scenario_greeting_templates", []))
    if not templates:
        return ""
    line = random.choice(templates).replace("{task}", task)
    return sanitize_scenario_greeting(line, max_chars)


def build_scenario_greeting_messages(
    context: dict[str, Any],
    max_chars: int = 80,
) -> list[dict[str, str]]:
    """Build API messages for one short, natural scenario greeting."""
    context_text = format_proactive_context(context)
    return [
        {
            "role": "system",
            "content": (
                "你是一个长期陪伴用户的桌面像素角色。"
                "请根据下面的简要上下文生成一句自然的主动问候。\n\n"
                "要求：\n"
                "- 只输出一句中文。\n"
                f"- 不要超过 {max_chars} 个中文字符。\n"
                "- 不要说“根据记忆”“你之前说过”“我读取到”。\n"
                "- 不要暴露 memory.json、Mem0、数据库、配置等技术细节。\n"
                "- 不要像任务管理器一样催促用户。\n"
                "- 语气自然、克制、有陪伴感。\n"
                "- 如果上下文显示用户可能在忙，请降低打扰感。\n"
                "- 可以轻轻关联用户近期关注点，但不要机械复述。\n"
                "- 只输出问候文本，不要输出解释、JSON 或多候选。"
            ),
        },
        {"role": "user", "content": f"上下文：\n{context_text}"},
    ]


def format_proactive_context(context: dict[str, Any]) -> str:
    """Format compact context into a short prompt-readable text block."""
    lines: list[str] = []
    _append_scalar(lines, "time_period", context.get("time_period"))
    _append_scalar(lines, "season", context.get("season"))
    _append_list(lines, "recent_task_focus", context.get("recent_task_focus", []))
    for section in ("communication_style", "companionship_style", "interaction_patterns"):
        values = context.get(section, {})
        if isinstance(values, dict) and values:
            rendered = ", ".join(
                f"{key}={_value_text(value)}"
                for key, value in values.items()
                if _value_text(value)
            )
            if rendered:
                lines.append(f"{section}: {rendered}")
    runtime = context.get("runtime_state", {})
    if isinstance(runtime, dict) and runtime:
        rendered_runtime = ", ".join(
            f"{key}={_value_text(value)}"
            for key, value in runtime.items()
            if _value_text(value)
        )
        if rendered_runtime:
            lines.append(f"runtime_state: {rendered_runtime}")
    return "\n".join(lines)


def sanitize_scenario_greeting(text: str, max_chars: int = 80) -> str:
    """Trim generated/local scenario greeting to a safe, single-line bubble text."""
    line = " ".join(str(text or "").split())
    if len(line) > max_chars:
        line = line[: max(0, max_chars - 1)].rstrip() + "…"
    return line


def is_scenario_greeting_acceptable(text: str) -> bool:
    line = str(text or "").strip()
    return bool(line) and not any(phrase in line for phrase in FORBIDDEN_GREETING_PHRASES)


def _pick_line(local_lines: dict[str, Any], group_name: str) -> str:
    lines = _string_items(local_lines.get(group_name, []))
    return random.choice(lines) if lines else ""


def _primary_task(context: dict[str, Any]) -> str:
    tasks = _string_items(context.get("recent_task_focus", []))
    return tasks[0] if tasks else ""


def _compact_mapping(source: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            items = _string_items(value)
            if items:
                compact[key] = items[:3]
        else:
            text = _string_value(value)
            if text:
                compact[key] = text
    return compact


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        if isinstance(value, str) and value.strip():
            return [_clip_text(value)]
        return []
    return [_clip_text(str(item).strip()) for item in value if str(item).strip()]


def _string_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    return _clip_text(str(value).strip())


def _clip_text(text: str, limit: int = 80) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _unique_limited(items: list[str], limit: int) -> list[str]:
    unique: list[str] = []
    for item in items:
        if item and item not in unique:
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _count_context_items(context: dict[str, Any]) -> int:
    count = len(_string_items(context.get("recent_task_focus", [])))
    for section in ("communication_style", "companionship_style", "interaction_patterns"):
        values = context.get(section, {})
        if isinstance(values, dict):
            for value in values.values():
                if isinstance(value, list):
                    count += len(_string_items(value))
                elif _string_value(value):
                    count += 1
    return count


def _append_scalar(lines: list[str], label: str, value: Any) -> None:
    text = _string_value(value)
    if text:
        lines.append(f"{label}: {text}")


def _append_list(lines: list[str], label: str, value: Any) -> None:
    items = _string_items(value)
    if items:
        lines.append(f"{label}: {', '.join(items)}")


def _value_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_string_items(value))
    return _string_value(value)
