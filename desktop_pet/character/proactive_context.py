from __future__ import annotations

import random
from typing import Any

from character.persona_state import compact_behavior_policy, read_persona_state
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


# 根据 memory、runtime_state、time_period 组装主动行为 上下文对象或消息并返回给调用方。
def build_proactive_context(
    memory: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
    time_period: str | None = None,
    season: str | None = None,
    character: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据 memory、runtime_state、time_period 组装主动行为 上下文对象或消息并返回给调用方。"""
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
    runtime = dict(runtime_state or {})
    persona_state = read_persona_state(runtime_state)
    for key, value in persona_state.to_dict().items():
        runtime.setdefault(key, value)

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
        "character_behavior": compact_behavior_policy(character),
        "runtime_state": runtime,
    }


# 判断主动上下文中是否包含足够的场景问候线索。
def has_scenario_context(context: dict[str, Any], min_items: int = 1) -> bool:
    """判断主动上下文中是否包含足够的场景问候线索。"""
    return _count_context_items(context) >= max(1, min_items)


# 根据 context、local_lines、max_chars 组装本地 场景 问候对象或消息并返回给调用方。
def build_local_scenario_greeting(
    context: dict[str, Any],
    local_lines: dict[str, Any],
    max_chars: int = 80,
    greeting_type: str = "memory_context_greeting",
) -> str:
    """根据 context、local_lines、max_chars 组装本地 场景 问候对象或消息并返回给调用方。"""
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


# 根据 context、max_chars 组装场景 问候 消息对象或消息并返回给调用方。
def build_scenario_greeting_messages(
    context: dict[str, Any],
    max_chars: int = 80,
) -> list[dict[str, str]]:
    """根据 context、max_chars 组装场景 问候 消息对象或消息并返回给调用方。"""
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
                "- 遵守角色行为策略，但不要逐字复述策略。\n"
                "- 如果上下文显示用户可能在忙，请降低打扰感。\n"
                "- 只有近期关注点与此刻明显相关时才轻轻带到，不要频繁引用长期记忆。\n"
                "- 不过度撒娇，不假装真人，不索取回应，不制造依赖。\n"
                "- 只输出问候文本，不要输出解释、JSON 或多候选。"
            ),
        },
        {"role": "user", "content": f"上下文：\n{context_text}"},
    ]


# 根据 context 整理format 主动行为 上下文，并把结果交给调用方或写回状态。
def format_proactive_context(context: dict[str, Any]) -> str:
    """根据 context 整理format 主动行为 上下文，并把结果交给调用方或写回状态。"""
    lines: list[str] = []
    _append_scalar(lines, "time_period", context.get("time_period"))
    _append_scalar(lines, "season", context.get("season"))
    _append_list(lines, "recent_task_focus", context.get("recent_task_focus", []))
    for section in (
        "communication_style",
        "companionship_style",
        "interaction_patterns",
        "character_behavior",
    ):
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


# 清理场景问候中的空白和记忆实现词，并限制最大长度。
def sanitize_scenario_greeting(text: str, max_chars: int = 80) -> str:
    """清理场景问候中的空白和记忆实现词，并限制最大长度。"""
    line = " ".join(str(text or "").split())
    if len(line) > max_chars:
        line = line[: max(0, max_chars - 1)].rstrip() + "…"
    return line


# 判断模型生成的场景问候是否避开记忆实现词并适合展示。
def is_scenario_greeting_acceptable(text: str) -> bool:
    """判断模型生成的场景问候是否避开记忆实现词并适合展示。"""
    line = str(text or "").strip()
    return bool(line) and not any(phrase in line for phrase in FORBIDDEN_GREETING_PHRASES)


# 根据 local_lines、group_name 从候选数据中选择台词并返回。
def _pick_line(local_lines: dict[str, Any], group_name: str) -> str:
    """根据 local_lines、group_name 从候选数据中选择台词并返回。"""
    lines = _string_items(local_lines.get(group_name, []))
    return random.choice(lines) if lines else ""


# 根据 context 提取当前最重要的任务或学习主题。
def _primary_task(context: dict[str, Any]) -> str:
    """根据 context 提取当前最重要的任务或学习主题。"""
    tasks = _string_items(context.get("recent_task_focus", []))
    return tasks[0] if tasks else ""


# 根据 source、keys 按指定键筛选字典内容，并丢弃空值。
def _compact_mapping(source: Any, keys: list[str]) -> dict[str, Any]:
    """根据 source、keys 按指定键筛选字典内容，并丢弃空值。"""
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


# 根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。
def _string_items(value: Any) -> list[str]:
    """根据 value 遍历嵌套数据中的文本项，过滤空值后逐条返回。"""
    if not isinstance(value, list):
        if isinstance(value, str) and value.strip():
            return [_clip_text(value)]
        return []
    return [_clip_text(str(item).strip()) for item in value if str(item).strip()]


# 根据 value 提取文本值并去除空白，无法使用时返回空字符串。
def _string_value(value: Any) -> str:
    """根据 value 提取文本值并去除空白，无法使用时返回空字符串。"""
    if value in (None, ""):
        return ""
    return _clip_text(str(value).strip())


# 按最大长度裁剪文本，超出时追加省略标记。
def _clip_text(text: str, limit: int = 80) -> str:
    """按最大长度裁剪文本，超出时追加省略标记。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# 根据 items、limit 去重并限制列表长度，保持原有顺序。
def _unique_limited(items: list[str], limit: int) -> list[str]:
    """根据 items、limit 去重并限制列表长度，保持原有顺序。"""
    unique: list[str] = []
    for item in items:
        if item and item not in unique:
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique


# 统计主动上下文中可用于问候的任务和关系条目数量。
def _count_context_items(context: dict[str, Any]) -> int:
    """统计主动上下文中可用于问候的任务和关系条目数量。"""
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


# 根据 lines、label、value 把scalar加入当前状态或持久化记录。
def _append_scalar(lines: list[str], label: str, value: Any) -> None:
    """根据 lines、label、value 把scalar加入当前状态或持久化记录。"""
    text = _string_value(value)
    if text:
        lines.append(f"{label}: {text}")


# 根据 lines、label、value 把list加入当前状态或持久化记录。
def _append_list(lines: list[str], label: str, value: Any) -> None:
    """根据 lines、label、value 把list加入当前状态或持久化记录。"""
    items = _string_items(value)
    if items:
        lines.append(f"{label}: {', '.join(items)}")


# 根据 value 提取文本值并去除空白，无法使用时返回空字符串。
def _value_text(value: Any) -> str:
    """根据 value 提取文本值并去除空白，无法使用时返回空字符串。"""
    if isinstance(value, list):
        return "、".join(_string_items(value))
    return _string_value(value)
