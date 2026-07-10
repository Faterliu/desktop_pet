from __future__ import annotations

import random
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QThread,
    QTimer,
    Signal,
    QObject,
    Slot,
)
from PySide6.QtGui import QAction, QCloseEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QWidget

from ai.context_manager import ContextManager
from ai.deepseek_client import DeepSeekClient, DeepSeekError
from ai.mem0_memory_service import Mem0MemoryService
from ai.prompt_builder import PromptBuilder
from ai.summarizer import Summarizer
from animation.sprite_player import SpritePlayer
from app.background_task_registry import BackgroundTaskRegistry
from app.bubble_position_service import BubblePositionService
from app.chat_input import ChatInput
from app.chat_flow_controller import ChatFlowController
from app.clipboard_service import ClipboardService
from app.config_service import ConfigService
from app.context_menu import build_context_menu
from app.formal_answer_panel import FormalAnswerPanel
from app.history_clear_worker import ChatHistoryClearWorker
from app.message_splitter import split_knowledge_bubble_text
from app.reminder_controller import ReminderController
from app.reminder_tool import ReminderTool, ReminderToolRequest
from app.speech_bubble import ReplyBubble, SpeechBubble
from app.window_position_service import WindowPositionService
from character.behavior_controller import BehaviorController
from character.proactive_context import (
    build_scenario_greeting_messages,
    is_scenario_greeting_acceptable,
    sanitize_scenario_greeting,
)
from storage.chat_store import ChatStore
from storage.json_store import load_json, load_json_prefer_primary, save_json
from storage.local_lines_service import LocalLinesService
from storage.memory_store import MemoryStore
from storage.memory_vector_store import MemoryVectorStore
from storage.reminder_store import ReminderStore
from storage.usage_store import UsageStore
from utils.dwm_border import apply_transparent_window_fixes, force_window_topmost, suppress_dwm_border
from utils.logger import get_logger


logger = get_logger(__name__)


LOCAL_LINE_REFRESH_LABELS = {
    "first_start": "首次启动问候",
    "startup": "启动问候",
    "idle": "空闲主动问候",
    "quiet": "安静陪伴问候",
    "encourage": "鼓励话术",
    "sleepy": "晚间提醒",
    "greeting_morning": "早晨问候",
    "greeting_noon": "中午问候",
    "greeting_afternoon": "下午问候",
    "greeting_evening": "晚间问候",
    "greeting_spring": "春季问候",
    "greeting_summer": "夏季问候",
    "greeting_autumn": "秋季问候",
    "greeting_winter": "冬季问候",
    "thinking": "思考等待话术",
    "api_error": "API 错误提示",
    "ignored": "取消置顶提示",
    "return_after_idle": "恢复置顶提示",
    "work_focus": "专注工作提醒",
    "break_reminder": "休息提醒",
    "comfort": "安慰话术",
    "happy": "开心反馈",
    "sad": "低落反馈",
    "waiting": "输入等待提醒",
    "feedback": "主动问候反馈",
    "scenario_greeting_templates": "场景问候模板",
    "low_interrupt": "低打扰问候",
    "knowledge_speak_intro": "知识问候前置提示",
    "farewell": "退出告别",
    "poetry": "诗歌话术",
    "reply": "知识问候回应气泡",
}

CLIPBOARD_ASSISTANT_INSTRUCTIONS = {
    "summarize": "总结下面文本的重点，使用清晰的要点，不补充原文没有的信息。",
    "translate": "翻译下面文本，准确保留原意；若原文主要是中文，则翻译为自然英文，否则翻译为自然中文。",
    "polish": "润色下面文本的表达，使其自然、清晰、通顺，并只输出润色后的版本。",
    "explain": "解释下面文本的含义、关键概念和可能的上下文；信息不足时请明确说明。",
    "answer": "把下面文本作为用户的问题或材料，给出准确、结构清晰、可执行的正式回答。",
}

CLIPBOARD_ASSISTANT_LABELS = {
    "summarize": "总结",
    "translate": "翻译",
    "polish": "润色",
    "explain": "解释",
    "answer": "正式回答",
}


# 根据 value、default 转换为正整数，失败或小于等于零时返回默认值。
def _positive_int(value: Any, default: int) -> int:
    """根据 value、default 转换为正整数，失败或小于等于零时返回默认值。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class ChatWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    # 初始化后台聊天任务，持有本次请求所需依赖。
    def __init__(
        self,
        user_message: str,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
        context_manager: ContextManager,
        formal_qa_mode: bool,
        mem0_memory_service: Mem0MemoryService | None = None,
        user_id: str = "default_user",
        app_config: dict[str, Any] | None = None,
        reminder_tool: ReminderTool | None = None,
    ) -> None:
        """初始化后台聊天任务，持有本次请求所需依赖。"""
        super().__init__()
        self.user_message = user_message
        self.client = client
        self.prompt_builder = prompt_builder
        self.context_manager = context_manager
        self.formal_qa_mode = formal_qa_mode
        self.mem0_memory_service = mem0_memory_service
        self.user_id = user_id
        self.app_config = app_config or {}
        self.reminder_tool = reminder_tool

    # 在工作线程中构建消息并请求模型回复。
    def run(self) -> None:
        """在工作线程中构建消息并请求模型回复。"""
        try:
            recent_messages = self.context_manager.recent_messages(self.formal_qa_mode)
            if (
                recent_messages
                and recent_messages[-1].get("role") == "user"
                and recent_messages[-1].get("content") == self.user_message
            ):
                recent_messages = recent_messages[:-1]
            relevant_memories = self._relevant_memories()
            messages = self.prompt_builder.build_messages(
                self.user_message,
                recent_messages,
                formal_qa_mode=self.formal_qa_mode,
                relevant_memories=relevant_memories,
                reminder_tool_guidance=self._reminder_tool_guidance(),
            )
            reply = self._request_chat_reply(messages)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected chat worker failure")
            self.failed.emit(f"我刚刚走神了一下：{exc}")

    # 在提醒工具可用时请求模型识别提醒意图，否则保持普通聊天请求。
    def _request_chat_reply(self, messages: list[dict[str, str]]) -> str:
        """在提醒工具可用时请求模型识别提醒意图，否则保持普通聊天请求。"""
        if self.reminder_tool is None or not self.reminder_tool.is_enabled():
            return self.client.chat(messages)

        response = self.client.chat_with_reminder_tools(
            messages,
            self._json_fallback_messages(messages),
        )
        if response.invalid_tool_calls:
            return response.reply
        if not response.reminder_calls:
            return response.reply or "我在这里哦。"

        results = self.reminder_tool.create_reminders(
            [ReminderToolRequest(call.title, call.due_at) for call in response.reminder_calls],
            source=f"model_tool_{response.protocol}",
        )
        if not all(result.success for result in results):
            return self._reminder_tool_failure_reply(results[0].code)
        return response.reply or self._reminder_created_reply(results)

    # 构建供模型调用提醒工具的时间与边界说明。
    def _reminder_tool_guidance(self) -> str | None:
        """构建供模型调用提醒工具的时间与边界说明。"""
        if self.reminder_tool is None or not self.reminder_tool.is_enabled():
            return None
        current_time = self.reminder_tool.now_provider().isoformat(timespec="seconds")
        return (
            "【本地提醒工具】当前设备本地时间为 "
            f"{current_time}。当且仅当用户明确要设置提醒，且提醒内容与具体时间完整时，"
            "调用 create_reminder。due_at 必须是无时区的 YYYY-MM-DDTHH:MM:SS 本地绝对时间；"
            "请把“明天”“半小时后”等换算为该格式。若用户只说“晚点”“下午”“之后”等含糊时间，"
            "不要调用工具，先追问准确日期和时间。一次最多创建 3 条提醒。"
        )

    # 为不支持原生工具调用的端点构建严格 JSON 降级协议。
    def _json_fallback_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """为不支持原生工具调用的端点构建严格 JSON 降级协议。"""
        protocol = {
            "role": "system",
            "content": (
                "当前端点不支持工具调用。请只输出一个 JSON 对象，严格形如 "
                '{"reply":"给用户的自然语言回复","reminders":[{"title":"提醒内容",'
                '"due_at":"YYYY-MM-DDTHH:MM:SS"}]}。若不应创建提醒或时间不明确，'
                '必须输出 reminders: [] 并在 reply 中追问或正常回答；不要输出 Markdown 或其他字段。'
            ),
        }
        if not messages:
            return [protocol]
        return [*messages[:-1], protocol, messages[-1]]

    # 根据模型工具调用失败码生成安全、简短的本地提示。
    def _reminder_tool_failure_reply(self, code: str) -> str:
        """根据模型工具调用失败码生成安全、简短的本地提示。"""
        messages = {
            "reminders_disabled": "提醒功能当前未启用。",
            "active_reminder_limit": "当前进行中的提醒已达到上限。",
            "invalid_or_past_due_at": "这个提醒时间已经过去或格式不对，请告诉我一个未来的准确时间。",
            "empty_title": "提醒内容不能为空。",
            "too_many_reminders": "一次最多可以设置 3 条提醒。",
        }
        return messages.get(code, "这个提醒暂时没有设置成功，请告诉我准确的日期、时间和内容。")

    # 在模型未给出文本确认时，根据创建结果生成本地确认语。
    def _reminder_created_reply(self, results: list[Any]) -> str:
        """在模型未给出文本确认时，根据创建结果生成本地确认语。"""
        reminders = [result.reminder for result in results if result.reminder]
        if len(reminders) == 1:
            reminder = reminders[0]
            return f"好，我会在 {reminder['due_at'].replace('T', ' ')} 提醒你：{reminder['title']}"
        return f"好，已为你设置 {len(reminders)} 条提醒。"

    # 检索与当前消息相关的长期记忆文本并返回。
    def _relevant_memories(self) -> str:
        """检索与当前消息相关的长期记忆文本并返回。"""
        memory_config = self.app_config.get("memory", {})
        if (
            not memory_config.get("enable_mem0", False)
            or not memory_config.get("inject_mem0_to_prompt", False)
            or self.mem0_memory_service is None
        ):
            return ""

        try:
            top_k = int(memory_config.get("mem0_search_top_k", 5))
        except (TypeError, ValueError):
            top_k = 5
        return self.mem0_memory_service.format_for_prompt(
            user_id=self.user_id,
            query=self.user_message,
            top_k=top_k,
        )


class UtilityPromptWorker(QObject):
    """在后台执行不写入聊天记录的剪贴板辅助请求。"""

    finished = Signal(str, str)
    failed = Signal(str)

    # 初始化剪贴板辅助任务所需的模式、文本和模型依赖。
    def __init__(
        self,
        mode: str,
        clipboard_text: str,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
    ) -> None:
        """初始化剪贴板辅助任务所需的模式、文本和模型依赖。"""
        super().__init__()
        self.mode = mode
        self.clipboard_text = clipboard_text
        self.client = client
        self.prompt_builder = prompt_builder

    # 构建独立提示并请求模型，不读取聊天历史、不触发记忆工具。
    def run(self) -> None:
        """构建独立提示并请求模型，不读取聊天历史、不触发记忆工具。"""
        try:
            instruction = CLIPBOARD_ASSISTANT_INSTRUCTIONS.get(self.mode)
            if not instruction:
                raise ValueError("不支持的剪贴板处理模式。")
            user_message = (
                f"【剪贴板助手任务】{instruction}\n\n"
                f"【待处理文本】\n{self.clipboard_text}"
            )
            messages = self.prompt_builder.build_messages(
                user_message,
                recent_messages=[],
                formal_qa_mode=True,
                max_user_message_chars=len(user_message),
            )
            self.finished.emit(self.mode, self.client.chat(messages))
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Clipboard assistant worker failed: mode=%s", self.mode)
            self.failed.emit(f"剪贴板处理失败：{exc}")


class ProactiveSpeakWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    # 初始化 API 主动说话测试任务。
    def __init__(
        self,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
    ) -> None:
        """初始化 API 主动说话测试任务。"""
        super().__init__()
        self.client = client
        self.prompt_builder = prompt_builder

    # 请求模型生成一条简短、温柔的主动问候。
    def run(self) -> None:
        """请求模型生成一条简短、温柔的主动问候。"""
        try:
            messages = self.prompt_builder.build_messages(
                "请你主动对用户说一句简短、温柔、不打扰的陪伴问候，不要超过两句话。",
                [],
            )
            reply = self.client.chat(messages)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected proactive API worker failure")
            self.failed.emit(f"测试 API 主动说话失败：{exc}")


class ScenarioGreetingWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        client: DeepSeekClient,
        context: dict[str, Any],
        fallback_line: str,
        max_chars: int = 80,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.client = client
        self.context = context
        self.fallback_line = fallback_line
        self.max_chars = max_chars

    # 在线程中执行 ScenarioGreetingWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 ScenarioGreetingWorker 的后台任务，并通过信号返回结果。"""
        try:
            messages = build_scenario_greeting_messages(self.context, self.max_chars)
            reply = sanitize_scenario_greeting(self.client.chat(messages), self.max_chars)
            if not is_scenario_greeting_acceptable(reply):
                reply = sanitize_scenario_greeting(self.fallback_line, self.max_chars)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected scenario greeting worker failure")
            self.failed.emit(f"场景化问候生成失败：{exc}")


class KnowledgeSpeakWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    # 初始化记忆增强的知识问候 API 任务。
    def __init__(
        self,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
        memory: dict[str, Any],
        mem0_memory_service: Mem0MemoryService | None = None,
        user_id: str = "default_user",
        use_mem0: bool = False,
        mem0_memory_context: str = "",
    ) -> None:
        """初始化记忆增强的知识问候 API 任务。"""
        super().__init__()
        self.client = client
        self.prompt_builder = prompt_builder
        self.memory = memory
        self.mem0_memory_service = mem0_memory_service
        self.user_id = user_id
        self.use_mem0 = use_mem0
        self.mem0_memory_context = mem0_memory_context

    # 基于用户记忆随机选取一个偏好方向，生成 2-3 句针对性知识问候。
    def run(self) -> None:
        """基于用户记忆随机选取一个偏好方向，生成 2-3 句针对性知识问候。"""
        try:
            user_profile = self.memory.get("user_profile", {})
            work_study = self.memory.get("work_study", {})
            prefs = user_profile.get("preferences", [])
            topics = work_study.get("current_learning_topics", [])
            projects = work_study.get("current_projects", [])
            all_context = "、".join(topics + projects) or "暂无"
            focus = random.choice(prefs) if prefs else "编程学习"
            mem0_memory_context = self._mem0_memory_context()
            if mem0_memory_context:
                all_context = mem0_memory_context

            prompt = (
                f"用户偏好中有一条是：{focus}。其他背景：{all_context}。"
                f"请针对「{focus}」这个方向，主动给用户提供一段简短有用的内容，"
                "比如一个实用技巧、一条学习建议、一个冷知识或效率方法。"
                "严格控制在 2-3 句话以内，温柔自然，不要像AI助手那样正式。"
                "请以「你知道吗」「说起来」「对了」「我突然想到」这类口语化开头来开始。"
            )
            messages = self.prompt_builder.build_messages(
                prompt,
                [],
                relevant_memories=mem0_memory_context,
            )
            reply = self.client.chat(messages)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected knowledge worker failure")
            self.failed.emit(f"知识问候走神了：{exc}")

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _mem0_memory_context(self) -> str:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
        if self.mem0_memory_context:
            return self.mem0_memory_context
        if not self.use_mem0 or self.mem0_memory_service is None:
            return ""

        queries = [
            "用户最近正在做的项目",
            "用户的学习目标和工作任务",
            "用户喜欢的陪伴方式",
            "用户希望被提醒或鼓励的事情",
            "用户的长期偏好",
        ]
        return self.mem0_memory_service.format_for_prompt(
            user_id=self.user_id,
            query=random.choice(queries),
            top_k=3,
        )


class Mem0InitializationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        app_config: dict[str, Any],
        existing_service: Mem0MemoryService | None = None,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.app_config = app_config
        self.existing_service = existing_service

    # 在线程中执行 Mem0InitializationWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 Mem0InitializationWorker 的后台任务，并通过信号返回结果。"""
        try:
            if self.existing_service is not None:
                self.existing_service.close()
            self.finished.emit(Mem0MemoryService(self.app_config))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Mem0 initialization worker failed")
            self.failed.emit(str(exc))


class Mem0SearchWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        mem0_memory_service: Mem0MemoryService,
        user_id: str,
        query: str,
        top_k: int,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.mem0_memory_service = mem0_memory_service
        self.user_id = user_id
        self.query = query
        self.top_k = top_k

    # 在线程中执行 Mem0SearchWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 Mem0SearchWorker 的后台任务，并通过信号返回结果。"""
        try:
            context = self.mem0_memory_service.format_for_prompt(
                user_id=self.user_id,
                query=self.query,
                top_k=self.top_k,
            )
            self.finished.emit(context)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Mem0 search worker failed")
            self.failed.emit(str(exc))


class MemorySemanticMergeWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        vector_store: MemoryVectorStore,
        memory_path: Path,
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.vector_store = vector_store
        self.memory_path = memory_path

    # 在线程中执行 MemorySemanticMergeWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 MemorySemanticMergeWorker 的后台任务，并通过信号返回结果。"""
        try:
            self.finished.emit(self.vector_store.run_due_semantic_merge(self.memory_path))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Semantic memory merge worker failed")
            self.failed.emit(str(exc))


class LocalLinesRefreshWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        client: DeepSeekClient,
        local_lines_service: LocalLinesService,
        targets: list[dict[str, Any]],
    ) -> None:
        """初始化当前对象及其依赖。"""
        super().__init__()
        self.client = client
        self.local_lines_service = local_lines_service
        self.targets = targets

    # 在线程中执行 LocalLinesRefreshWorker 的后台任务，并通过信号返回结果。
    def run(self) -> None:
        """在线程中执行 LocalLinesRefreshWorker 的后台任务，并通过信号返回结果。"""
        try:
            if not self.targets:
                self.finished.emit({"refreshed": False, "reason": "no_enabled_groups", "results": []})
                return
            if not self.client.is_configured():
                self.finished.emit({"refreshed": False, "reason": "api_not_configured", "results": []})
                return

            results = []
            for target in self.targets:
                group = str(target.get("group", "")).strip()
                if not group:
                    continue
                interval_days = _positive_int(target.get("interval_days"), 14)
                monthly_refresh = bool(target.get("monthly_refresh", False))
                if not self.local_lines_service.should_refresh_generated_lines(
                    group,
                    interval_days=interval_days,
                    monthly_refresh=monthly_refresh,
                ):
                    results.append({"refreshed": False, "reason": "not_due", "group": group})
                    continue

                max_chars = _positive_int(target.get("max_chars"), 80)
                max_items = _positive_int(target.get("max_items"), 8)
                label = str(target.get("label", group)).strip() or group
                reply = self.client.chat(self._messages(group, label, max_items, max_chars))
                candidates = self._parse_lines(reply)
                result = self.local_lines_service.replace_generated_lines(
                    group,
                    candidates,
                    source="deepseek",
                    max_chars=max_chars,
                    max_items=max_items,
                )
                results.append(
                    {
                        "refreshed": result.saved,
                        "group": group,
                        "accepted_count": len(result.accepted),
                        "rejected_count": len(result.rejected),
                    }
                )

            self.finished.emit(
                {
                    "refreshed": any(item.get("refreshed") for item in results),
                    "results": results,
                }
            )
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Local lines refresh worker failed")
            self.failed.emit(str(exc))

    # 根据 group、label、max_items 限制消息数量和长度，返回符合预算的消息列表。
    def _messages(
        self,
        group: str,
        label: str,
        max_items: int,
        max_chars: int,
    ) -> list[dict[str, str]]:
        """根据 group、label、max_items 限制消息数量和长度，返回符合预算的消息列表。"""
        return [
            {
                "role": "system",
                "content": (
                    "你是 Windows 桌面 AI 宠物“小桃”的本地话术编辑器。"
                    "只输出中文短句列表，不要解释，不要编号，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"为本地话术分组“{label}”（配置键：{group}）生成 {max_items} 条中文短句。"
                    f"每条不超过 {max_chars} 个汉字或字符。"
                    "语气轻松温柔，不要说“根据记忆”“你之前说过”“数据库”“Mem0”“memory.json”。"
                    "贴合该分组用途，每行一条。"
                ),
            },
        ]

    # 解析用户输入的多行台词，并过滤空白行。
    def _parse_lines(self, text: str) -> list[str]:
        """解析用户输入的多行台词，并过滤空白行。"""
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            line = line.lstrip("-*0123456789.、)） \t").strip()
            if line:
                lines.append(line.strip('"“”'))
        if lines:
            return lines
        stripped = text.strip()
        return [stripped] if stripped else []


class DesktopPetWindow(QWidget):
    # 初始化桌宠主窗口、依赖模块与 UI 组件。
    def __init__(self, project_root: Path) -> None:
        """初始化桌宠主窗口、依赖模块与 UI 组件。"""
        super().__init__()
        self.project_root = project_root
        self.assets_dir = self.project_root / "assets"
        self.config_dir = self.project_root / "config"
        self.data_dir = self.project_root / "data"

        self.config_path = self.config_dir / "app_config.json"
        self.example_config_path = self.config_dir / "app_config.example.json"
        self.character_path = self.config_dir / "character_default.json"
        self.local_lines_path = self.config_dir / "local_lines.json"
        self.safety_rules_path = self.config_dir / "safety_rules.json"
        self.sprite_config_path = self.assets_dir / "sprite_config.json"
        self.chat_history_formal_path = self.data_dir / "chat_history_formal.json"
        self.chat_history_informal_path = self.data_dir / "chat_history_informal.json"
        self.summary_formal_path = self.data_dir / "conversation_summary_formal.json"
        self.summary_informal_path = self.data_dir / "conversation_summary_informal.json"
        self.memory_path = self.data_dir / "memory.json"
        self.daily_usage_path = self.data_dir / "daily_usage.json"
        self.reminders_path = self.data_dir / "reminders.json"
        self.window_state_path = self.data_dir / "window_state.json"

        self.app_config = self._load_app_config()
        self.config_service = ConfigService(self.app_config)
        self.local_lines_service = LocalLinesService(
            self.local_lines_path,
            self.data_dir / "local_lines_generated_meta.json",
        )
        self.window_position_service = WindowPositionService(
            self.window_state_path,
            QApplication,
        )
        self.bubble_position_service = BubblePositionService(QApplication)
        self.mem0_memory_service: Mem0MemoryService | None = None
        self.drag_start_offset = QPoint()
        self.dragging = False
        self.mouse_press_position = QPoint()
        self.chat_thread: QThread | None = None
        self.chat_worker: QObject | None = None
        self.clipboard_thread: QThread | None = None
        self.clipboard_worker: QObject | None = None
        self._pending_scenario_fallback_line = ""
        self.clear_history_thread: QThread | None = None
        self.clear_history_worker: QObject | None = None
        self.mem0_init_thread: QThread | None = None
        self.mem0_init_worker: QObject | None = None
        self.mem0_search_thread: QThread | None = None
        self.mem0_search_worker: QObject | None = None
        self.memory_maintenance_thread: QThread | None = None
        self.memory_maintenance_worker: QObject | None = None
        self.local_lines_refresh_thread: QThread | None = None
        self.local_lines_refresh_worker: QObject | None = None
        self.background_tasks = BackgroundTaskRegistry(default_wait_timeout_ms=1000)
        self.move_animation: QPropertyAnimation | None = None
        self.behavior_started = False
        self.reminders_started = False
        self.memory_maintenance_started = False
        self.local_lines_refresh_started = False
        self.exit_animation_in_progress = False
        self.allow_immediate_close = False
        self._close_after_workers_finished = False
        self._is_closing = False
        self._summaries_running: set[str] = set()
        self._suppress_click = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._open_chat_input)
        self._waiting_timer = QTimer(self)
        self._waiting_timer.setSingleShot(True)
        self._waiting_timer.timeout.connect(self._show_waiting_prompt)
        self.formal_answer_panels: list[FormalAnswerPanel] = []
        self.active_formal_answer_panel: FormalAnswerPanel | None = None
        self.pending_formal_question = ""
        self._pending_was_formal = False
        self._pending_knowledge_mem0_context = ""

        self.chat_store_formal = ChatStore(self.chat_history_formal_path)
        self.chat_store_informal = ChatStore(self.chat_history_informal_path)
        self.usage_store = UsageStore(self.daily_usage_path)
        self.reminder_store = ReminderStore(self.reminders_path)
        self.clipboard_service = ClipboardService()
        self.reminder_tool = ReminderTool(
            self.reminder_store,
            enabled_provider=self._reminders_enabled,
            max_active_provider=self._max_active_reminders,
        )
        self.reminder_controller = ReminderController(
            self.reminder_store,
            enabled=self._reminders_enabled(),
            check_interval_seconds=self._reminder_check_interval_seconds(),
            can_deliver=self._can_deliver_reminders,
            parent=self,
        )
        self.memory_vector_store = MemoryVectorStore(
            self.data_dir / "memory_vectors.json",
            self.app_config,
        )
        self.memory_store = MemoryStore(self.memory_path, self.memory_vector_store)
        self.deepseek_client = DeepSeekClient(self.config_path, self.example_config_path)
        self.chat_flow_controller = ChatFlowController(
            self.chat_store_formal,
            self.chat_store_informal,
            self._formal_qa_enabled,
            self._api_chat_enabled,
            self.deepseek_client.is_configured,
            self._generate_local_reply,
        )
        self.prompt_builder = PromptBuilder(
            self.character_path,
            self.safety_rules_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
            self.config_path,
            self.example_config_path,
        )
        self.context_manager = ContextManager(
            self.config_path,
            self.chat_store_formal,
            self.chat_store_informal,
            self.example_config_path,
        )
        self.summarizer_formal = Summarizer(
            self.summary_formal_path,
            self.chat_store_formal,
            self.memory_store,
            self.deepseek_client,
            mem0_memory_service=self.mem0_memory_service,
            user_id=self._memory_user_id(),
            config_path=self.config_path,
            fallback_config_path=self.example_config_path,
        )
        self.summarizer_informal = Summarizer(
            self.summary_informal_path,
            self.chat_store_informal,
            self.memory_store,
            self.deepseek_client,
            mem0_memory_service=self.mem0_memory_service,
            user_id=self._memory_user_id(),
            config_path=self.config_path,
            fallback_config_path=self.example_config_path,
        )

        self.sprite_player = SpritePlayer(self.sprite_config_path, self._ui_scale())
        self.bubble = SpeechBubble()
        self.reply_bubble = ReplyBubble()
        self.chat_input = ChatInput()
        self.behavior_controller = BehaviorController(
            self.config_path,
            self.local_lines_path,
            self.usage_store,
            self._config_snapshot,
            self._has_knowledge_memory,
            config_saver=self._save_app_config,
            character_path=self.character_path,
        )
        self.auto_move_timer = QTimer(self)
        self.auto_move_timer.timeout.connect(self._trigger_auto_move)
        self._topmost_enforcement_timer = QTimer(self)
        self._topmost_enforcement_timer.timeout.connect(self._enforce_topmost)
        self._local_lines_refresh_timer = QTimer(self)
        self._local_lines_refresh_timer.timeout.connect(self._start_local_lines_refresh_worker)
        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._restore_position()
        self._refresh_auto_move_timer()
        self._update_sprite(self.sprite_player.current_pixmap())
        self.sprite_player.set_action("idle")
        self._start_mem0_initialization(close_existing=False)

    # 设置主窗口的透明、无边框和置顶属性。
    def _setup_window(self) -> None:
        """设置主窗口的透明、无边框和置顶属性。"""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if self.config_service.get_bool("ui.always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("DesktopPetWindow { background: transparent; border: none; }")

    # 创建用于显示精灵帧的标签并设置初始尺寸。
    def _setup_ui(self) -> None:
        """创建用于显示精灵帧的标签并设置初始尺寸。"""
        self.sprite_label = QLabel(self)
        self.sprite_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.sprite_label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.sprite_label.setAutoFillBackground(False)
        self.sprite_label.setStyleSheet("QLabel { background: transparent; border: none; }")
        self.sprite_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        width, height = self.sprite_player.base_size()
        self.resize(width, height)
        self.sprite_label.setGeometry(0, 0, width, height)

    # 连接动画、输入框和主动行为等信号。
    def _connect_signals(self) -> None:
        """连接动画、输入框和主动行为等信号。"""
        self.sprite_player.frame_changed.connect(self._update_sprite)
        self.chat_input.message_submitted.connect(self._handle_user_message)
        self.behavior_controller.speak_requested.connect(self._handle_behavior_speak)
        self.behavior_controller.knowledge_speak_requested.connect(self._handle_knowledge_speak)
        self.behavior_controller.scenario_greeting_requested.connect(
            self._handle_scenario_greeting
        )
        self.reply_bubble.clicked.connect(self._handle_reply_bubble_clicked)
        self.reminder_controller.reminder_due.connect(self._handle_due_reminder)

    # 窗口首次显示时启动主动行为控制器和置顶强制计时器。
    def showEvent(self, event) -> None:  # noqa: N802
        """窗口首次显示时启动主动行为控制器和置顶强制计时器。"""
        super().showEvent(event)
        if not self.behavior_started:
            self.behavior_started = True
            self.behavior_controller.start()
        if not self.reminders_started:
            self.reminders_started = True
            self.reminder_controller.start()
        if not self.memory_maintenance_started:
            self.memory_maintenance_started = True
            QTimer.singleShot(0, self._start_memory_maintenance_worker)
        if not self.local_lines_refresh_started:
            self.local_lines_refresh_started = True
            QTimer.singleShot(0, self._start_local_lines_refresh_worker)
            self._local_lines_refresh_timer.start(6 * 60 * 60 * 1000)
        apply_transparent_window_fixes(self)
        self._enforce_topmost()
        self._topmost_enforcement_timer.start(30_000)
        pixmap = self.sprite_label.pixmap()
        if pixmap:
            self._apply_sprite_window_mask(pixmap)

    # 移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。
    def nativeEvent(self, eventType, message) -> tuple:  # noqa: N802
        """移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。"""
        ok, result = suppress_dwm_border(eventType, message)
        if ok:
            return True, result
        return super().nativeEvent(eventType, message)

    # 处理鼠标按下事件，用于拖拽和右键菜单。
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标按下事件，用于拖拽和右键菜单。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.drag_start_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.mouse_press_position = event.globalPosition().toPoint()
            if self.move_animation and self.move_animation.state() == QPropertyAnimation.State.Running:
                self.move_animation.stop()
                self.sprite_player.set_action("idle")
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    # 处理鼠标移动事件，实现拖拽桌宠。
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标移动事件，实现拖拽桌宠。"""
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.mouse_press_position
            if delta.manhattanLength() > 6:
                self.dragging = True
                self.move(event.globalPosition().toPoint() - self.drag_start_offset)
        super().mouseMoveEvent(event)

    # 窗口位置变化时同步悬浮气泡和输入框的位置。
    def moveEvent(self, event) -> None:  # noqa: N802
        """窗口位置变化时同步悬浮气泡和输入框的位置。"""
        super().moveEvent(event)
        self._sync_floating_widgets()

    # 处理鼠标释放事件，区分点击聊天和拖拽结束；双击通过计时器抑制单击。
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标释放事件，区分点击聊天和拖拽结束；双击通过计时器抑制单击。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self._save_window_position()
            elif self.config_service.get_bool("ui.click_to_chat", True):
                if self._suppress_click:
                    self._suppress_click = False
                else:
                    self._click_timer.start(QApplication.doubleClickInterval())
        super().mouseReleaseEvent(event)

    # 双击人物视为回复/打招呼；若在主动问候后窗口内则回复 feedback 话术。
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """双击人物视为回复/打招呼；若在主动问候后窗口内则回复 feedback 话术。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._suppress_click = True
            if self.behavior_controller.is_within_proactive_reply_window():
                reply = self.behavior_controller.pick_feedback_line()
                self.behavior_controller.notify_proactive_response()
            else:
                reply = self.behavior_controller.pick_reply_line()
            if reply:
                self.behavior_controller.notify_user_interaction()
                self.sprite_player.set_action("waving")
                self._display_message(reply, 7000, "system")
        super().mouseDoubleClickEvent(event)

    # 关闭窗口前保存位置并安全回收后台线程。
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """关闭窗口前保存位置并安全回收后台线程。"""
        self._is_closing = True
        if not self.allow_immediate_close:
            self.reminder_controller.stop()
            event.ignore()
            self.request_exit()
            return
        if self._background_workers_running():
            self._close_after_workers_finished = True
            running_tasks = self._stop_background_workers()
            if running_tasks:
                logger.warning("Waiting for unfinished background tasks before close: %s", running_tasks)
                event.ignore()
                return
            self._close_after_workers_finished = False
        self._destroy_formal_answer_panels()
        self.reminder_controller.stop()
        self._save_window_position()
        self.bubble.hide()
        self.reply_bubble.hide()
        self.chat_input.hide()
        if self.mem0_memory_service is not None:
            self.mem0_memory_service.close()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # 在指定屏幕坐标位置弹出右键菜单。
    def _show_context_menu(self, global_pos: QPoint) -> None:
        """在指定屏幕坐标位置弹出右键菜单。"""
        menu = build_context_menu(
            self,
            test_action_handler=self._handle_test_action,
            on_test_move_left=self._test_move_left,
            on_test_move_right=self._test_move_right,
            on_test_jump=self._test_jump,
            on_test_proactive_speak=self._test_proactive_speak_once,
            on_test_idle_prompt=self._test_idle_prompt_once,
            on_test_api_proactive_speak=self._test_api_proactive_speak_once,
            on_test_knowledge_speak=self._test_knowledge_speak_once,
            on_test_poetry=self._test_poetry,
            on_request_exit=self.request_exit,
            current_scale=self._ui_scale(),
            do_not_disturb=self.config_service.get_bool("behavior.do_not_disturb", False),
            auto_move=self.config_service.get_bool("ui.enable_free_move", False),
            api_chat_enabled=self.config_service.get_bool("api.enable_chat_api", True),
            api_provider=self._api_provider(),
            formal_qa_mode=self._formal_qa_enabled(),
            formal_answer_display=self._formal_answer_display_mode(),
            on_set_scale=self._set_scale,
            on_custom_scale=self._open_scale_dialog,
            on_toggle_dnd=self._toggle_do_not_disturb,
            on_toggle_auto_move=self._toggle_auto_move,
            on_toggle_api_chat=self._toggle_api_chat,
            on_set_api_provider=self._set_api_provider,
            on_toggle_formal_qa_mode=self._toggle_formal_qa_mode,
            on_set_formal_answer_display=self._set_formal_answer_display,
            on_toggle_always_on_top=self._toggle_always_on_top,
            on_reload_config=self._reload_config,
            always_on_top=self.config_service.get_bool("ui.always_on_top", True),
            show_test_menu=self.config_service.get_bool("ui.show_test_menu", False),
            show_clear_menu=self.config_service.get_bool("ui.show_clear_menu", False),
            show_reload_config=self.config_service.get_bool("ui.show_reload_config", True),
            on_clear_informal_chat=self._clear_informal_chat_history,
            on_clear_formal_chat=self._clear_formal_chat_history,
            on_add_ten_minute_reminder=self._add_ten_minute_reminder,
            on_add_custom_minute_reminder=self._add_custom_minute_reminder,
            on_view_current_reminders=self._view_current_reminders,
            on_clear_completed_reminders=self._clear_completed_reminders,
            on_clipboard_assistant=self._handle_clipboard_assistant,
        )
        menu.exec(global_pos)

    # 响应菜单中的测试动作切换请求。
    def _handle_test_action(self, action_name: str) -> None:
        """响应菜单中的测试动作切换请求。"""
        if action_name == "idle":
            self.sprite_player.set_action("idle")
            return
        self.sprite_player.set_action(action_name, fallback_action="idle", force_single_cycle=True)

    # 请求优雅退出：播放 waving 并显示道别语，再关闭窗口。
    def request_exit(self) -> None:
        """请求优雅退出：播放 waving 并显示道别语，再关闭窗口。"""
        if self.allow_immediate_close or self.exit_animation_in_progress:
            return

        self.exit_animation_in_progress = True
        self.chat_input.hide()
        farewell = self.behavior_controller.pick_farewell_line()
        self.sprite_player.set_action("waving", fallback_action="idle", force_single_cycle=True)
        duration_ms = self.sprite_player.action_duration_ms("waving", force_single_cycle=True)
        if farewell:
            self.bubble.show_message(farewell, self.geometry(), duration_ms + 400, "system")
        else:
            self.bubble.hide()
        QTimer.singleShot(duration_ms + 50, self._finalize_exit)

    # 在退出动作播放完成后真正关闭程序。
    def _finalize_exit(self) -> None:
        """在退出动作播放完成后真正关闭程序。"""
        self.allow_immediate_close = True
        self.close()

    # 手动触发一次主动说话，便于测试气泡与动作。
    def _test_proactive_speak_once(self) -> None:
        """手动触发一次主动说话，便于测试气泡与动作。"""
        if self.behavior_controller.trigger_test_speak():
            return
        self._display_message("本地话术里暂时没有可测试的内容。", 3200, "system")

    # 手动触发一次空闲问候逻辑，测试内容比例分流（普通/知识）。
    def _test_idle_prompt_once(self) -> None:
        """手动触发一次空闲问候逻辑，测试内容比例分流（普通/知识）。"""
        if self._chat_in_progress():
            self._display_message("麻烦等我一下下。", 3200, "system")
            return
        result = self.behavior_controller.trigger_test_idle_prompt()
        if result.startswith("未触发"):
            self._display_message(result, 3500, "system")

    # 手动测试人物向左平滑移动。
    def _test_move_left(self) -> None:
        """手动测试人物向左平滑移动。"""
        QTimer.singleShot(120, lambda: self._start_horizontal_move_test(-140))

    # 手动测试人物向右平滑移动。
    def _test_move_right(self) -> None:
        """手动测试人物向右平滑移动。"""
        QTimer.singleShot(120, lambda: self._start_horizontal_move_test(140))

    # 手动测试人物原地跳跃。
    def _test_jump(self) -> None:
        """手动测试人物原地跳跃。"""
        QTimer.singleShot(120, self._run_jump_test)

    # 在菜单关闭后真正执行一次原地跳跃测试。
    def _run_jump_test(self) -> None:
        """在菜单关闭后真正执行一次原地跳跃测试。"""
        if self._movement_locked():
            return
        screen = self._current_screen()
        if not screen:
            return
        self._start_jump_auto_move(self.pos(), screen.availableGeometry())

    # 手动触发一次 API 主动说话，便于测试联网和主动气泡。
    def _test_api_proactive_speak_once(self) -> None:
        """手动触发一次 API 主动说话，便于测试联网和主动气泡。"""
        if self._chat_in_progress():
            self._display_message("我还在忙上一个问题呢，等我一下下。", 3200, "system")
            return
        if not self.deepseek_client.is_configured():
            self._display_message(
                "还没有配置可用的 API key，暂时没法测试 API 主动说话哦。",
                4200,
                "system",
            )
            return

        self.sprite_player.set_action("waving")
        self._display_message("我在努力思考，想要和你打个招呼。", 2800, "system")
        self._start_proactive_api_worker()

    # 手动触发一次知识问候，便于测试记忆增强内容和气泡。
    def _test_knowledge_speak_once(self) -> None:
        """手动触发一次知识问候，便于测试记忆增强内容和气泡。"""
        if self._chat_in_progress():
            self._display_message("我还在忙上一条请求呢，等我一下下。", 3200, "system")
            return
        self._handle_knowledge_speak()

    # 念一首诗，将换行诗文字展示为气泡消息。
    def _test_poetry(self) -> None:
        """念一首诗，将换行诗文字展示为气泡消息。"""
        line = self.behavior_controller.pick_poetry_line()
        if line:
            self.sprite_player.set_action("running", force_single_cycle=True)
            self._display_message(line, 12000, "system")

    # 设置人物显示缩放比例并持久化到配置文件。
    def _set_scale(self, scale: float) -> None:
        """设置人物显示缩放比例并持久化到配置文件。"""
        normalized_scale = max(0.3, min(scale, 3.0))
        self.app_config.setdefault("ui", {})["scale"] = round(normalized_scale, 2)
        self.sprite_player.set_scale(normalized_scale)
        self._resize_for_sprite()
        self._save_app_config()
        self._display_message(f"人物大小已调整为 {normalized_scale:.2f}x。", 2800, "system")

    # 弹出自定义缩放输入框，让用户手动设置人物大小。
    def _open_scale_dialog(self) -> None:
        """弹出自定义缩放输入框，让用户手动设置人物大小。"""
        current_scale = self._ui_scale()
        new_scale, accepted = QInputDialog.getDouble(
            self,
            "自定义缩放",
            "请输入人物缩放倍数：",
            value=current_scale,
            minValue=0.3,
            maxValue=3.0,
            decimals=2,
        )
        if accepted:
            self._set_scale(new_scale)

    # 通过菜单添加固定 10 分钟后的提醒。
    def _add_ten_minute_reminder(self) -> None:
        """通过菜单添加固定 10 分钟后的提醒。"""
        title, accepted = QInputDialog.getText(self, "10 分钟后提醒", "提醒内容：")
        if accepted:
            self._create_reminder_after_minutes(title, 10, "menu_10_minutes")

    # 通过菜单添加用户指定分钟数后的提醒。
    def _add_custom_minute_reminder(self) -> None:
        """通过菜单添加用户指定分钟数后的提醒。"""
        minutes, accepted = QInputDialog.getInt(
            self,
            "添加自定义分钟提醒",
            "多少分钟后提醒：",
            value=30,
            minValue=1,
            maxValue=7 * 24 * 60,
        )
        if not accepted:
            return
        title, accepted = QInputDialog.getText(self, "添加自定义分钟提醒", "提醒内容：")
        if accepted:
            self._create_reminder_after_minutes(title, minutes, "menu_custom_minutes")

    # 创建相对当前时间的提醒，并显示创建结果。
    def _create_reminder_after_minutes(self, title: str, minutes: int, source: str) -> bool:
        """创建相对当前时间的提醒，并显示创建结果。"""
        normalized_title = title.strip()
        if not self._reminders_enabled():
            self._display_message("提醒功能当前未启用。", 3200, "system")
            return False
        if not normalized_title:
            self._display_message("提醒内容不能为空。", 3200, "system")
            return False
        if minutes <= 0:
            self._display_message("提醒分钟数需要大于 0。", 3200, "system")
            return False
        if len(self.reminder_store.list_reminders("active")) >= self._max_active_reminders():
            self._display_message("当前进行中的提醒已达到上限。", 3500, "system")
            return False

        self.reminder_store.add_reminder(
            normalized_title,
            datetime.now() + timedelta(minutes=minutes),
            source=source,
        )
        self._display_message(f"好，{minutes} 分钟后提醒你：{normalized_title}", 4200, "system")
        return True

    # 显示仍在进行中的提醒列表。
    def _view_current_reminders(self) -> None:
        """显示仍在进行中的提醒列表。"""
        reminders = self.reminder_store.list_reminders("active")
        if not reminders:
            self._display_message("当前没有进行中的提醒。", 3200, "system")
            return
        preview = [
            f"{item['due_at'].replace('T', ' ')}：{item['title']}"
            for item in reminders[:3]
        ]
        suffix = f"\n还有 {len(reminders) - 3} 条提醒。" if len(reminders) > 3 else ""
        self._display_message("当前提醒：\n" + "\n".join(preview) + suffix, 8500, "system")

    # 清理已完成提醒，不影响仍在进行中的提醒。
    def _clear_completed_reminders(self) -> None:
        """清理已完成提醒，不影响仍在进行中的提醒。"""
        removed_count = self.reminder_store.clear_completed_reminders()
        self._display_message(
            f"已清空 {removed_count} 条已完成提醒。" if removed_count else "没有已完成提醒可清空。",
            3200,
            "system",
        )

    # 按菜单选择主动读取剪贴板，并启动独立的后台辅助请求。
    def _handle_clipboard_assistant(self, mode: str) -> None:
        """按菜单选择主动读取剪贴板，并启动独立的后台辅助请求。"""
        if mode not in CLIPBOARD_ASSISTANT_INSTRUCTIONS:
            self._display_message("不支持这个剪贴板处理方式。", 3200, "system")
            return
        if not self._clipboard_assistant_enabled():
            self._display_message("剪贴板助手当前未启用。", 3200, "system")
            return

        clipboard_text = self.clipboard_service.read_text().strip()
        if not clipboard_text:
            self._display_message("剪贴板里没有可处理的文字内容。", 3200, "system")
            return

        max_chars = self._clipboard_max_chars()
        truncated = len(clipboard_text) > max_chars
        if truncated:
            clipboard_text = clipboard_text[:max_chars]
        logger.info(
            "Clipboard assistant requested: mode=%s chars=%s truncated=%s",
            mode,
            len(clipboard_text),
            truncated,
        )

        if not self._api_chat_enabled():
            self._display_message("聊天 API 当前已关闭，暂时不能处理剪贴板内容。", 3600, "system")
            return
        if not self.deepseek_client.is_configured():
            self._display_message("还没有配置可用的 API key，暂时不能处理剪贴板内容。", 4200, "system")
            return
        if self.background_tasks.is_registered("clipboard_assistant"):
            self._display_message("我正在处理上一段剪贴板内容，请稍等一下。", 3200, "system")
            return

        self.sprite_player.set_action("review")
        self._display_message("我来看看剪贴板里的内容。", 2800, "system")
        self._start_clipboard_assistant_worker(mode, clipboard_text)

    # 接收提醒控制器的到期事件，并用挥手动作和气泡展示提醒。
    def _handle_due_reminder(self, reminder: dict[str, str]) -> None:
        """接收提醒控制器的到期事件，并用挥手动作和气泡展示提醒。"""
        if self._closing_or_closed():
            return
        title = str(reminder.get("title", "")).strip()
        if not title:
            return
        self.sprite_player.set_action("waving", fallback_action="idle", force_single_cycle=True)
        self._display_message(f"提醒你一下：{title}", 8000, "reminder")

    # 切换免打扰模式并保存配置。
    def _toggle_do_not_disturb(self, enabled: bool) -> None:
        """切换免打扰模式并保存配置。"""
        self.app_config.setdefault("behavior", {})["do_not_disturb"] = enabled
        self._save_app_config()
        if enabled and self.bubble.source == "proactive":
            self.bubble.hide()
        self._display_message("小桃接下来不会说话了。" if enabled else "来和小桃聊天吧。", 3000, "system")
        if not enabled:
            self.reminder_controller.check_due_reminders()

    # 切换自主移动功能并刷新定时器。
    def _toggle_auto_move(self, enabled: bool) -> None:
        """切换自主移动功能并刷新定时器。"""
        self.app_config.setdefault("ui", {})["enable_free_move"] = enabled
        self._save_app_config()
        self._refresh_auto_move_timer()
        self._display_message("小桃跑起来了！" if enabled else "我不会乱动啦。", 3000, "system")

    # 切换用户聊天时是否调用外部 API。
    def _toggle_api_chat(self, enabled: bool) -> None:
        """切换用户聊天时是否调用外部 API。"""
        self.app_config.setdefault("api", {})["enable_chat_api"] = enabled
        self._save_app_config()
        self._display_message("我变的更聪明了。" if enabled else "我好像变笨了。", 3200, "system")

    # 切换聊天模型提供商并保存配置。
    def _set_api_provider(self, provider: str) -> None:
        """切换聊天模型提供商并保存配置。"""
        normalized = "openai" if provider == "openai" else "deepseek"
        self.app_config.setdefault("api", {})["provider"] = normalized
        self._save_app_config()
        label = "OpenAI GPT" if normalized == "openai" else "DeepSeek"
        self._display_message(f"聊天模型已切换为 {label}。", 3200, "system")

    # 切换正式问答模式。
    def _toggle_formal_qa_mode(self, enabled: bool) -> None:
        """切换正式问答模式。"""
        self._chat_config()["formal_qa_mode"] = enabled
        self._save_app_config()
        if not enabled:
            self._destroy_formal_answer_panels()
        self._display_message(
            "我会更加认真地回答你的问题。" if enabled else "现在就简简单单的聊天吧。",
            3200,
            "system",
        )

    # 切换正式问答多回答显示方式。
    def _set_formal_answer_display(self, mode: str) -> None:
        """切换正式问答多回答显示方式。"""
        normalized_mode = mode if mode in {"new_panel", "append"} else "new_panel"
        self._chat_config()["formal_answer_display"] = normalized_mode
        self._save_app_config()
        message = (
            "正式问答将为每个新问题保留并新建文本框。"
            if normalized_mode == "new_panel"
            else "正式问答将把新回答追加到同一个文本框。"
        )
        self._display_message(message, 3600, "system")

    # 切换窗口置顶状态，开启时回复 return_after_idle，关闭时回复 ignored。
    def _toggle_always_on_top(self, enabled: bool) -> None:
        """切换窗口置顶状态，开启时回复 return_after_idle，关闭时回复 ignored。"""
        self._ui_config()["always_on_top"] = enabled
        self._save_app_config()
        self._reapply_window_flags()
        self.show()
        self.raise_()
        apply_transparent_window_fixes(self)
        self.chat_input.set_always_on_top(enabled)
        self.reply_bubble.set_always_on_top(enabled)
        if enabled:
            self._topmost_enforcement_timer.start(30_000)
            reply = self.behavior_controller.pick_return_after_idle_line()
        else:
            self._topmost_enforcement_timer.stop()
            reply = self.behavior_controller.pick_ignored_line()
        if reply:
            self._display_message(reply, 5000, "system")

    # 根据当前配置重建窗口标志，不依赖 setWindowFlag 的单属性切换。
    def _reapply_window_flags(self) -> None:
        """根据当前配置重建窗口标志，不依赖 setWindowFlag 的单属性切换。"""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if self.config_service.get_bool("ui.always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # 清空正式与非正式聊天历史及对应摘要数据。
    def _clear_chat_history(self) -> None:
        """清空正式与非正式聊天历史及对应摘要数据。"""
        default_summary = {
            "summary": "",
            "covered_message_count": 0,
            "highlights": [],
            "last_updated": "",
        }
        for store, summary_path in [
            (self.chat_store_formal, self.summary_formal_path),
            (self.chat_store_informal, self.summary_informal_path),
        ]:
            store.clear_history()
            save_json(summary_path, default_summary)
        self._display_message("我会用心记住你说过的话哦", 3500, "system")

    # 清空非正式聊天历史；若配置开启则在清空前强制总结。
    def _clear_informal_chat_history(self) -> None:
        """清空非正式聊天历史；若配置开启则在清空前强制总结。"""
        self._start_clear_history_worker(
            "informal",
            self.summarizer_informal,
            self.chat_store_informal,
        )

    # 清空正式问答聊天历史；若配置开启则在清空前强制总结。
    def _clear_formal_chat_history(self) -> None:
        """清空正式问答聊天历史；若配置开启则在清空前强制总结。"""
        self._start_clear_history_worker(
            "formal",
            self.summarizer_formal,
            self.chat_store_formal,
        )

    # 创建聊天历史清理后台任务并注册生命周期回调。
    def _start_clear_history_worker(
        self,
        mode: str,
        summarizer: Summarizer,
        chat_store: ChatStore,
    ) -> None:
        """创建聊天历史清理后台任务并注册生命周期回调。"""
        if self.background_tasks.is_registered("clear_history"):
            return

        self.clear_history_thread = QThread(self)
        self.clear_history_worker = ChatHistoryClearWorker(
            mode=mode,
            summarizer=summarizer,
            chat_store=chat_store,
            force_summarize=self.config_service.get_bool(
                "chat.force_summarize_before_clear",
                True,
            ),
        )
        self.clear_history_worker.moveToThread(self.clear_history_thread)
        self.clear_history_thread.started.connect(self.clear_history_worker.run)
        self.clear_history_worker.finished.connect(self._on_clear_history_success)
        self.clear_history_worker.failed.connect(self._on_clear_history_failure)
        self.clear_history_worker.finished.connect(self.clear_history_thread.quit)
        self.clear_history_worker.failed.connect(self.clear_history_thread.quit)
        self.clear_history_thread.finished.connect(self._cleanup_clear_history_thread)
        if not self._register_background_task(
            "clear_history",
            self.clear_history_thread,
            self.clear_history_worker,
            self._clear_history_task_refs,
        ):
            self._discard_unregistered_task(
                self.clear_history_thread,
                self.clear_history_worker,
                self._clear_history_task_refs,
            )
            return
        self.clear_history_thread.start()

    # 显示聊天历史清理成功提示，并释放后台任务引用。
    def _on_clear_history_success(self, mode: str) -> None:
        """显示聊天历史清理成功提示，并释放后台任务引用。"""
        if self._closing_or_closed():
            return
        label = "这些知识真有趣呢" if mode == "formal" else "我会好好保存我们聊天的回忆哦"
        self._display_message(f"{label}", 3500, "system")

    # 显示聊天历史清理失败提示，并释放后台任务引用。
    def _on_clear_history_failure(self, mode: str, error_message: str) -> None:
        """显示聊天历史清理失败提示，并释放后台任务引用。"""
        if self._closing_or_closed():
            return
        label = "正式问答记录" if mode == "formal" else "非正式聊天记录"
        self._display_message(f"{label}清理失败：{error_message}", 5000, "assistant")

    # 重新读取配置文件，并刷新动画和行为控制状态。
    def _reload_config(self) -> None:
        """重新读取配置文件，并刷新动画和行为控制状态。"""
        self.app_config = self._load_app_config()
        self.config_service.update(self.app_config)
        self.reminder_controller.configure(
            self._reminders_enabled(),
            self._reminder_check_interval_seconds(),
        )
        self.memory_vector_store.update_config(self.app_config)
        self._start_mem0_initialization(close_existing=True)
        self.summarizer_formal.user_id = self._memory_user_id()
        self.summarizer_informal.user_id = self._memory_user_id()
        self.sprite_player.set_scale(self._ui_scale())
        self.sprite_player.load()
        self._setup_window()
        self._resize_for_sprite()
        self.show()
        self.raise_()
        apply_transparent_window_fixes(self)
        self._refresh_auto_move_timer()
        self.behavior_controller.reload()
        self._display_message("嘿嘿，我更了解你了。", 3500, "system")

    # 在宠物附近打开输入框；若有主动气泡则先关闭。
    def _open_chat_input(self) -> None:
        """在宠物附近打开输入框；若有主动气泡则先关闭。"""
        if self.bubble.source == "proactive":
            self.bubble.hide()
        if self._chat_in_progress():
            self._display_message("我还在想上一条呢，等我一下下。", 3200, "system")
            return
        if self._clear_history_in_progress():
            self._display_message("先等一下，我正在整理笔记。", 3200, "system")
            return
        self.behavior_controller.notify_user_interaction()
        self.chat_input.set_always_on_top(self.config_service.get_bool("ui.always_on_top", True))
        self.chat_input.show_near(self.geometry())
        self.sprite_player.set_action("waiting", fallback_action="idle", force_single_cycle=True)
        self._waiting_timer.start(30_000)

    _poetry_keywords = {"诗", "诗歌", "写诗", "念诗", "吟诗", "背诗", "来首", "作诗", "赋诗"}
    _remind_command_pattern = re.compile(r"^/remind\s+(\d+)\s+(.+?)\s*$", re.IGNORECASE)

    # 处理用户提交的消息，并决定走占位回复还是 API 回复。
    def _handle_user_message(self, message: str) -> None:
        """处理用户提交的消息，并决定走占位回复还是 API 回复。"""
        if re.match(r"^\s*/remind(?:\s|$)", message, re.IGNORECASE):
            self._waiting_timer.stop()
            self._handle_remind_command(message)
            return
        self._waiting_timer.stop()
        if self._clear_history_in_progress():
            self._display_message("先等一下，我正在整理笔记。", 3200, "system")
            return
        self.behavior_controller.notify_user_interaction()
        chat_context = self.chat_flow_controller.begin_user_message(message)
        self._sync_chat_flow_state()

        if (
            self._is_poetry_request(message)
            and not self._api_chat_enabled()
            and not self._formal_qa_enabled()
            and not self.config_service.get_bool("ui.enable_free_move", False)
            and not self.config_service.get_bool("ui.always_on_top", True)
        ):
            poetry_line = self.behavior_controller.pick_poetry_line()
            if poetry_line:
                self.chat_flow_controller.append_assistant_reply(chat_context, poetry_line)
                self.sprite_player.set_action("running", force_single_cycle=True)
                self._show_answer_output(poetry_line, source="assistant", question=message)
                return

        self._display_message("我收到啦，让我想一想。", 3200, "system")
        self.sprite_player.set_action("review" if len(message) > 24 else "running")

        decision = self.chat_flow_controller.decide_after_thinking(chat_context)
        if decision.kind == "local_reply":
            self.sprite_player.set_action("idle")
            self._show_answer_output(decision.reply, source="assistant", question=decision.question)
            return

        if decision.kind == "missing_api_config":
            self.sprite_player.set_action("failed")
            self._show_answer_output(decision.reply, source="assistant", question=decision.question)
            return

        self._start_chat_worker(message)

    # 解析并执行轻量的 /remind 分钟数 提醒内容 本地命令。
    def _handle_remind_command(self, message: str) -> None:
        """解析并执行轻量的 /remind 分钟数 提醒内容 本地命令。"""
        match = self._remind_command_pattern.match(message.strip())
        if match is None:
            self._display_message("用法：/remind 分钟数 提醒内容", 3600, "system")
            return
        minutes = int(match.group(1))
        if minutes <= 0:
            self._display_message("提醒分钟数需要大于 0。", 3200, "system")
            return
        self._create_reminder_after_minutes(match.group(2), minutes, "chat_command")

    # 检查用户消息是否包含念诗/写诗相关的关键词。
    def _is_poetry_request(self, message: str) -> bool:
        """检查用户消息是否包含念诗/写诗相关的关键词。"""
        return any(kw in message for kw in self._poetry_keywords)

    # 在本地模式下按当前问答风格生成回复。
    def _generate_local_reply(self, message: str, formal_qa_mode: bool = False) -> str:
        """在本地模式下按当前问答风格生成回复。"""
        stripped_message = message.strip()
        if not stripped_message:
            return "我在这里哦。"
        if formal_qa_mode:
            if "?" in stripped_message or "？" in stripped_message:
                return (
                    "我先认真回答你一下：现在我没有接入外部问答能力，所以没法像联网模式那样给你完整检索和推理结果。"
                    "不过如果你愿意，我仍然可以基于你提供的信息，帮你一起拆问题、列思路、整理步骤。"
                )
            return (
                f"我已经完整记住你刚刚说的内容：{stripped_message[:60]}。"
                "当前是正式问答模式，但我现在走的是本地回复，所以没法给出特别深入的答案。"
                "如果你打开 API，我就可以尽量给你更完整、更有条理的回答。"
            )
        if "?" in stripped_message or "？" in stripped_message:
            return "这个问题我先记住啦。现在我没有连上 API，所以只能先陪你整理思路；如果你愿意，我也可以继续听你说。"
        if any(keyword in stripped_message for keyword in ["你好", "在吗", "嗨", "hi", "hello"]):
            return "我在这里哦，很高兴你来找我。"
        if any(keyword in stripped_message for keyword in ["累", "烦", "难", "焦虑", "紧张"]):
            return "抱抱你呀，先别急，我们可以一点点来。虽然我现在没接 API，但我会认真陪着你。"
        return f"我收到啦：{stripped_message[:30]}。现在我先用本地模式陪你，如果你想要更完整的回答，可以再打开 API。"

    # 创建后台线程执行模型请求，避免阻塞界面。
    def _start_chat_worker(self, message: str) -> None:
        """创建后台线程执行模型请求，避免阻塞界面。"""
        if not self.chat_flow_controller.can_start_chat(
            self.background_tasks.is_registered("chat")
        ):
            return

        self.chat_thread = QThread(self)
        self.chat_worker = ChatWorker(
            **self.chat_flow_controller.chat_worker_kwargs(
                message,
                client=self.deepseek_client,
                prompt_builder=self.prompt_builder,
                context_manager=self.context_manager,
                mem0_memory_service=self.mem0_memory_service,
                user_id=self._memory_user_id(),
                app_config=self.app_config,
                reminder_tool=self.reminder_tool,
            )
        )
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._on_chat_success)
        self.chat_worker.failed.connect(self._on_chat_failure)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        if not self._register_background_task(
            "chat",
            self.chat_thread,
            self.chat_worker,
            self._clear_chat_task_refs,
        ):
            self._discard_unregistered_task(
                self.chat_thread,
                self.chat_worker,
                self._clear_chat_task_refs,
            )
            return
        self.chat_thread.start()

    # 创建后台线程执行 API 主动说话测试。
    def _start_proactive_api_worker(self) -> None:
        """创建后台线程执行 API 主动说话测试。"""
        if self.background_tasks.is_registered("chat"):
            return

        self.chat_thread = QThread(self)
        self.chat_worker = ProactiveSpeakWorker(
            self.deepseek_client,
            self.prompt_builder,
        )
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._on_proactive_api_success)
        self.chat_worker.failed.connect(self._on_proactive_api_failure)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        if not self._register_background_task(
            "chat",
            self.chat_thread,
            self.chat_worker,
            self._clear_chat_task_refs,
        ):
            self._discard_unregistered_task(
                self.chat_thread,
                self.chat_worker,
                self._clear_chat_task_refs,
            )
            return
        self.chat_thread.start()

    # 创建独立后台线程处理剪贴板内容，不接入聊天记录与摘要流程。
    def _start_clipboard_assistant_worker(self, mode: str, clipboard_text: str) -> None:
        """创建独立后台线程处理剪贴板内容，不接入聊天记录与摘要流程。"""
        if self.background_tasks.is_registered("clipboard_assistant"):
            return

        self.clipboard_thread = QThread(self)
        self.clipboard_worker = UtilityPromptWorker(
            mode,
            clipboard_text,
            self.deepseek_client,
            self.prompt_builder,
        )
        self.clipboard_worker.moveToThread(self.clipboard_thread)
        self.clipboard_thread.started.connect(self.clipboard_worker.run)
        self.clipboard_worker.finished.connect(self._on_clipboard_assistant_success)
        self.clipboard_worker.failed.connect(self._on_clipboard_assistant_failure)
        self.clipboard_worker.finished.connect(self.clipboard_thread.quit)
        self.clipboard_worker.failed.connect(self.clipboard_thread.quit)
        self.clipboard_thread.finished.connect(self._cleanup_clipboard_assistant_thread)
        if not self._register_background_task(
            "clipboard_assistant",
            self.clipboard_thread,
            self.clipboard_worker,
            self._clear_clipboard_assistant_task_refs,
        ):
            self._discard_unregistered_task(
                self.clipboard_thread,
                self.clipboard_worker,
                self._clear_clipboard_assistant_task_refs,
            )
            return
        self.clipboard_thread.start()

    # 在线程结束后清理工作对象和线程对象。
    def _cleanup_chat_thread(self) -> None:
        """在线程结束后清理工作对象和线程对象。"""
        self.background_tasks.unregister("chat", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 清理聊天记录后台线程。
    def _cleanup_clear_history_thread(self) -> None:
        """清理聊天记录后台线程。"""
        self.background_tasks.unregister("clear_history", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 清理剪贴板辅助后台线程。
    def _cleanup_clipboard_assistant_thread(self) -> None:
        """清理剪贴板辅助后台线程。"""
        self.background_tasks.unregister("clipboard_assistant", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 清空聊天线程和 worker 引用，避免回调重复清理。
    def _clear_chat_task_refs(self) -> None:
        """清空聊天线程和 worker 引用，避免回调重复清理。"""
        self.chat_worker = None
        self.chat_thread = None

    # 清空剪贴板辅助线程和 worker 引用。
    def _clear_clipboard_assistant_task_refs(self) -> None:
        """清空剪贴板辅助线程和 worker 引用。"""
        self.clipboard_worker = None
        self.clipboard_thread = None

    # 清空历史清理线程和 worker 引用。
    def _clear_history_task_refs(self) -> None:
        """清空历史清理线程和 worker 引用。"""
        self.clear_history_worker = None
        self.clear_history_thread = None

    # 清空 Mem0 初始化线程和 worker 引用。
    def _clear_mem0_init_task_refs(self) -> None:
        """清空 Mem0 初始化线程和 worker 引用。"""
        self.mem0_init_worker = None
        self.mem0_init_thread = None

    # 清空 Mem0 搜索线程和 worker 引用。
    def _clear_mem0_search_task_refs(self) -> None:
        """清空 Mem0 搜索线程和 worker 引用。"""
        self.mem0_search_worker = None
        self.mem0_search_thread = None

    # 清空记忆维护线程和 worker 引用。
    def _clear_memory_maintenance_task_refs(self) -> None:
        """清空记忆维护线程和 worker 引用。"""
        self.memory_maintenance_worker = None
        self.memory_maintenance_thread = None

    # 清空本地台词刷新线程和 worker 引用。
    def _clear_local_lines_refresh_task_refs(self) -> None:
        """清空本地台词刷新线程和 worker 引用。"""
        self.local_lines_refresh_worker = None
        self.local_lines_refresh_thread = None

    # 把线程和 worker 注册到后台任务表，并绑定清理回调。
    def _register_background_task(
        self,
        name: str,
        thread: QThread,
        worker: QObject,
        cleanup,
        wait_timeout_ms: int | None = None,
    ) -> bool:
        """把线程和 worker 注册到后台任务表，并绑定清理回调。"""
        return self.background_tasks.register(
            name,
            thread,
            worker,
            cleanup=cleanup,
            wait_timeout_ms=wait_timeout_ms,
        )

    # 根据 thread、worker、cleanup 丢弃未注册完成的线程和 worker 引用。
    def _discard_unregistered_task(self, thread: QThread, worker: QObject, cleanup) -> None:
        """根据 thread、worker、cleanup 丢弃未注册完成的线程和 worker 引用。"""
        try:
            worker.deleteLater()
            thread.deleteLater()
        except RuntimeError:
            pass
        cleanup()

    # 整理mem 0 init wait timeout ms，并把结果交给调用方或写回状态。
    def _mem0_init_wait_timeout_ms(self) -> int:
        """整理mem 0 init wait timeout ms，并把结果交给调用方或写回状态。"""
        try:
            timeout_seconds = float(
                self.config_service.get("memory.mem0_init_timeout_seconds", 10)
            )
        except (TypeError, ValueError):
            timeout_seconds = 10.0
        return max(0, int(timeout_seconds * 1000))

    # 判断主窗口是否正在关闭或已经关闭。
    def _closing_or_closed(self) -> bool:
        """判断主窗口是否正在关闭或已经关闭。"""
        return self._is_closing or self._close_after_workers_finished

    # 根据 service 更新mem0记忆服务状态，并同步相关缓存或界面。
    def _set_mem0_memory_service(self, service: Mem0MemoryService | None) -> None:
        """根据 service 更新mem0记忆服务状态，并同步相关缓存或界面。"""
        self.mem0_memory_service = service
        self.summarizer_formal.mem0_memory_service = service
        self.summarizer_informal.mem0_memory_service = service

    # 启动 Mem0 初始化后台任务，避免阻塞主界面。
    def _start_mem0_initialization(self, close_existing: bool) -> None:
        """启动 Mem0 初始化后台任务，避免阻塞主界面。"""
        if self.background_tasks.is_registered("mem0_init"):
            return

        existing_service = self.mem0_memory_service if close_existing else None
        if close_existing:
            self._set_mem0_memory_service(None)
            self._pending_knowledge_mem0_context = ""

        self.mem0_init_thread = QThread(self)
        self.mem0_init_worker = Mem0InitializationWorker(
            self.app_config,
            existing_service=existing_service,
        )
        self.mem0_init_worker.moveToThread(self.mem0_init_thread)
        self.mem0_init_thread.started.connect(self.mem0_init_worker.run)
        self.mem0_init_worker.finished.connect(self._on_mem0_initialization_success)
        self.mem0_init_worker.failed.connect(self._on_mem0_initialization_failure)
        self.mem0_init_worker.finished.connect(self.mem0_init_thread.quit)
        self.mem0_init_worker.failed.connect(self.mem0_init_thread.quit)
        self.mem0_init_thread.finished.connect(self._cleanup_mem0_init_thread)
        if not self._register_background_task(
            "mem0_init",
            self.mem0_init_thread,
            self.mem0_init_worker,
            self._clear_mem0_init_task_refs,
            wait_timeout_ms=self._mem0_init_wait_timeout_ms(),
        ):
            self._discard_unregistered_task(
                self.mem0_init_thread,
                self.mem0_init_worker,
                self._clear_mem0_init_task_refs,
            )
            return
        self.mem0_init_thread.start()

    # 保存初始化完成的 Mem0 服务并释放任务引用。
    def _on_mem0_initialization_success(self, service: object) -> None:
        """保存初始化完成的 Mem0 服务并释放任务引用。"""
        if self._closing_or_closed():
            if isinstance(service, Mem0MemoryService):
                service.close()
            return
        if isinstance(service, Mem0MemoryService):
            self._set_mem0_memory_service(service)

    # 记录 Mem0 初始化失败并释放初始化任务引用。
    def _on_mem0_initialization_failure(self, error_message: str) -> None:
        """记录 Mem0 初始化失败并释放初始化任务引用。"""
        logger.warning("Mem0 initialization failed: %s", error_message)
        if self._closing_or_closed():
            return
        self._set_mem0_memory_service(None)

    # 清理mem0init线程线程注册和关联引用。
    def _cleanup_mem0_init_thread(self) -> None:
        """清理mem0init线程线程注册和关联引用。"""
        self.background_tasks.unregister("mem0_init", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 启动 Mem0 检索后台任务，为知识问候准备语义上下文。
    def _start_mem0_search_worker(self) -> None:
        """启动 Mem0 检索后台任务，为知识问候准备语义上下文。"""
        if self.background_tasks.is_registered("mem0_search"):
            return
        if self.mem0_memory_service is None or not self.mem0_memory_service.is_available():
            return

        self.mem0_search_thread = QThread(self)
        self.mem0_search_worker = Mem0SearchWorker(
            self.mem0_memory_service,
            user_id=self._memory_user_id(),
            query="用户最近正在做的项目、学习目标、长期偏好和希望被提醒的事情",
            top_k=3,
        )
        self.mem0_search_worker.moveToThread(self.mem0_search_thread)
        self.mem0_search_thread.started.connect(self.mem0_search_worker.run)
        self.mem0_search_worker.finished.connect(self._on_mem0_search_success)
        self.mem0_search_worker.failed.connect(self._on_mem0_search_failure)
        self.mem0_search_worker.finished.connect(self.mem0_search_thread.quit)
        self.mem0_search_worker.failed.connect(self.mem0_search_thread.quit)
        self.mem0_search_thread.finished.connect(self._cleanup_mem0_search_thread)
        if not self._register_background_task(
            "mem0_search",
            self.mem0_search_thread,
            self.mem0_search_worker,
            self._clear_mem0_search_task_refs,
        ):
            self._discard_unregistered_task(
                self.mem0_search_thread,
                self.mem0_search_worker,
                self._clear_mem0_search_task_refs,
            )
            return
        self.mem0_search_thread.start()

    # 保存 Mem0 检索文本，并继续知识问候生成流程。
    def _on_mem0_search_success(self, context: str) -> None:
        """保存 Mem0 检索文本，并继续知识问候生成流程。"""
        if self._closing_or_closed():
            return
        self._pending_knowledge_mem0_context = context
        if not context or self._chat_in_progress() or self.chat_input.isVisible():
            return
        self.behavior_controller.notify_proactive_shown("extra_knowledge")
        self._handle_knowledge_speak()

    # 记录 Mem0 检索失败，并继续使用空记忆上下文。
    def _on_mem0_search_failure(self, error_message: str) -> None:
        """记录 Mem0 检索失败，并继续使用空记忆上下文。"""
        logger.warning("Mem0 knowledge search failed: %s", error_message)
        if self._closing_or_closed():
            return
        self._pending_knowledge_mem0_context = ""

    # 清理mem0search线程线程注册和关联引用。
    def _cleanup_mem0_search_thread(self) -> None:
        """清理mem0search线程线程注册和关联引用。"""
        self.background_tasks.unregister("mem0_search", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 启动记忆维护后台任务，同步向量索引和语义去重。
    def _start_memory_maintenance_worker(self) -> None:
        """启动记忆维护后台任务，同步向量索引和语义去重。"""
        if self.background_tasks.is_registered("memory_maintenance"):
            return
        self.memory_vector_store.update_config(self.app_config)
        if not self.config_service.get_bool("memory.enable_semantic_memory_merge", True):
            return

        self.memory_maintenance_thread = QThread(self)
        self.memory_maintenance_worker = MemorySemanticMergeWorker(
            self.memory_vector_store,
            self.memory_path,
        )
        self.memory_maintenance_worker.moveToThread(self.memory_maintenance_thread)
        self.memory_maintenance_thread.started.connect(self.memory_maintenance_worker.run)
        self.memory_maintenance_worker.finished.connect(self._on_memory_maintenance_success)
        self.memory_maintenance_worker.failed.connect(self._on_memory_maintenance_failure)
        self.memory_maintenance_worker.finished.connect(self.memory_maintenance_thread.quit)
        self.memory_maintenance_worker.failed.connect(self.memory_maintenance_thread.quit)
        self.memory_maintenance_thread.finished.connect(self._cleanup_memory_maintenance_thread)
        if not self._register_background_task(
            "memory_maintenance",
            self.memory_maintenance_thread,
            self.memory_maintenance_worker,
            self._clear_memory_maintenance_task_refs,
        ):
            self._discard_unregistered_task(
                self.memory_maintenance_thread,
                self.memory_maintenance_worker,
                self._clear_memory_maintenance_task_refs,
            )
            return
        self.memory_maintenance_thread.start()

    # 记录记忆维护完成，并释放维护任务引用。
    def _on_memory_maintenance_success(self, result: object) -> None:
        """记录记忆维护完成，并释放维护任务引用。"""
        if self._closing_or_closed():
            return
        if isinstance(result, dict) and int(result.get("merged_count", 0) or 0) > 0:
            logger.info("Semantic memory merge completed: %s", result)

    # 记录记忆维护失败，并释放维护任务引用。
    def _on_memory_maintenance_failure(self, error_message: str) -> None:
        """记录记忆维护失败，并释放维护任务引用。"""
        if self._closing_or_closed():
            return
        logger.warning("Semantic memory maintenance failed: %s", error_message)

    # 清理记忆maintenance线程线程注册和关联引用。
    def _cleanup_memory_maintenance_thread(self) -> None:
        """清理记忆maintenance线程线程注册和关联引用。"""
        self.background_tasks.unregister("memory_maintenance", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 为待刷新台词组创建 API 刷新后台任务。
    def _start_local_lines_refresh_worker(self) -> None:
        """为待刷新台词组创建 API 刷新后台任务。"""
        if self.background_tasks.is_registered("local_lines_refresh"):
            return
        if not self.config_service.get_bool("local_lines_refresh.enabled", True):
            return

        targets = self._local_lines_refresh_targets()
        if not targets:
            return

        self.local_lines_refresh_thread = QThread(self)
        self.local_lines_refresh_worker = LocalLinesRefreshWorker(
            self.deepseek_client,
            self.local_lines_service,
            targets=targets,
        )
        self.local_lines_refresh_worker.moveToThread(self.local_lines_refresh_thread)
        self.local_lines_refresh_thread.started.connect(self.local_lines_refresh_worker.run)
        self.local_lines_refresh_worker.finished.connect(self._on_local_lines_refresh_success)
        self.local_lines_refresh_worker.failed.connect(self._on_local_lines_refresh_failure)
        self.local_lines_refresh_worker.finished.connect(self.local_lines_refresh_thread.quit)
        self.local_lines_refresh_worker.failed.connect(self.local_lines_refresh_thread.quit)
        self.local_lines_refresh_thread.finished.connect(self._cleanup_local_lines_refresh_thread)
        if not self._register_background_task(
            "local_lines_refresh",
            self.local_lines_refresh_thread,
            self.local_lines_refresh_worker,
            self._clear_local_lines_refresh_task_refs,
        ):
            self._discard_unregistered_task(
                self.local_lines_refresh_thread,
                self.local_lines_refresh_worker,
                self._clear_local_lines_refresh_task_refs,
            )
            return
        self.local_lines_refresh_thread.start()

    # 筛选需要 API 刷新的本地台词组名称。
    def _local_lines_refresh_targets(self) -> list[dict[str, Any]]:
        """筛选需要 API 刷新的本地台词组名称。"""
        refresh_config = self.app_config.get("local_lines_refresh", {})
        if not isinstance(refresh_config, dict):
            return []
        groups_config = refresh_config.get("groups", {})
        if not isinstance(groups_config, dict):
            return []

        default_interval = _positive_int(refresh_config.get("interval_days"), 14)
        default_max_chars = _positive_int(refresh_config.get("max_chars"), 80)
        default_max_items = _positive_int(refresh_config.get("max_items"), 8)
        default_monthly_refresh = bool(refresh_config.get("monthly_refresh", False))
        targets: list[dict[str, Any]] = []

        for group, config in groups_config.items():
            if not isinstance(config, dict) or not config.get("enabled", False):
                continue
            group_name = str(group).strip()
            if not group_name:
                continue
            targets.append(
                {
                    "group": group_name,
                    "label": str(
                        config.get("label")
                        or LOCAL_LINE_REFRESH_LABELS.get(group_name)
                        or group_name
                    ),
                    "interval_days": _positive_int(config.get("interval_days"), default_interval),
                    "monthly_refresh": bool(config.get("monthly_refresh", default_monthly_refresh)),
                    "max_chars": _positive_int(config.get("max_chars"), default_max_chars),
                    "max_items": _positive_int(config.get("max_items"), default_max_items),
                }
            )
        return targets

    # 处理本地台词刷新结果，并提示用户刷新数量。
    def _on_local_lines_refresh_success(self, result: object) -> None:
        """处理本地台词刷新结果，并提示用户刷新数量。"""
        if self._closing_or_closed():
            return
        if isinstance(result, dict) and result.get("refreshed"):
            logger.info("Local lines refresh completed: %s", result)

    # 记录本地台词刷新失败，并释放刷新任务引用。
    def _on_local_lines_refresh_failure(self, error_message: str) -> None:
        """记录本地台词刷新失败，并释放刷新任务引用。"""
        if self._closing_or_closed():
            return
        logger.warning("Local lines refresh failed: %s", error_message)

    # 清理本地台词refresh线程线程注册和关联引用。
    def _cleanup_local_lines_refresh_thread(self) -> None:
        """清理本地台词refresh线程线程注册和关联引用。"""
        self.background_tasks.unregister("local_lines_refresh", delete_later=True)
        self._maybe_close_after_workers_finished()

    # 处理模型成功返回后的界面更新与消息落盘。
    def _on_chat_success(self, reply: str) -> None:
        """处理模型成功返回后的界面更新与消息落盘。"""
        if self._closing_or_closed():
            return
        completion = self.chat_flow_controller.complete_success(reply)
        self._sync_chat_flow_state()
        self.sprite_player.set_action("idle")
        self._show_answer_output(
            completion.reply,
            source="assistant",
            question=completion.question,
        )
        self._start_summary_task(completion.formal_qa_mode)

    # 处理模型请求失败后的动作和气泡提示。
    def _on_chat_failure(self, error_message: str) -> None:
        """处理模型请求失败后的动作和气泡提示。"""
        if self._closing_or_closed():
            return
        failure = self.chat_flow_controller.complete_failure(error_message)
        self._sync_chat_flow_state()
        self.sprite_player.set_action("failed")
        self._display_message(failure.error_message, 12000, "assistant")

    # 展示剪贴板辅助结果；此路径不写入聊天记录，也不会触发摘要或记忆更新。
    def _on_clipboard_assistant_success(self, mode: str, reply: str) -> None:
        """展示剪贴板辅助结果；此路径不写入聊天记录，也不会触发摘要或记忆更新。"""
        if self._closing_or_closed():
            return
        cleaned_reply = reply.strip() or "没有得到可显示的处理结果。"
        self.sprite_player.set_action("idle")
        if len(cleaned_reply) > 360:
            self._show_clipboard_assistant_panel(mode, cleaned_reply)
            return
        self._display_message(cleaned_reply, self._assistant_reply_bubble_duration_ms(), "assistant")

    # 展示剪贴板辅助失败提示，不影响当前聊天状态和历史数据。
    def _on_clipboard_assistant_failure(self, error_message: str) -> None:
        """展示剪贴板辅助失败提示，不影响当前聊天状态和历史数据。"""
        if self._closing_or_closed():
            return
        self.sprite_player.set_action("failed")
        self._display_message(error_message, 10000, "assistant")

    # 处理 API 主动说话测试成功后的界面更新。
    def _on_proactive_api_success(self, reply: str) -> None:
        """处理 API 主动说话测试成功后的界面更新。"""
        if self._closing_or_closed():
            return
        cleaned_reply = reply.strip() or "我在这里哦。"
        self.sprite_player.set_action("idle")
        self._display_message(cleaned_reply, 12000, "assistant")

    # 处理 API 主动说话测试失败后的界面更新。
    def _on_proactive_api_failure(self, error_message: str) -> None:
        """处理 API 主动说话测试失败后的界面更新。"""
        if self._closing_or_closed():
            return
        self.sprite_player.set_action("failed")
        self._display_message(error_message, 12000, "assistant")

    # 在后台线程中尝试触发对应模式的聊天摘要。
    def _maybe_summarize(self, formal_qa_mode: bool = False) -> None:
        """在后台线程中尝试触发对应模式的聊天摘要。"""
        try:
            trigger_rounds = self.config_service.get_int("api.summary_trigger_rounds", 12)
            if formal_qa_mode:
                self.summarizer_formal.maybe_summarize(trigger_rounds)
            else:
                self.summarizer_informal.maybe_summarize(trigger_rounds)
        except Exception:  # noqa: BLE001
            logger.exception("Background summarization failed")

    # 在线程中执行摘要压缩任务，避免阻塞界面。
    def _start_summary_task(self, formal_qa_mode: bool) -> None:
        """在线程中执行摘要压缩任务，避免阻塞界面。"""
        mode = "formal" if formal_qa_mode else "informal"
        if mode in self._summaries_running or self._closing_or_closed():
            return
        self._summaries_running.add(mode)

        # 整理run 摘要，并把结果交给调用方或写回状态。
        def run_summary() -> None:
            """整理run 摘要，并把结果交给调用方或写回状态。"""
            try:
                self._maybe_summarize(formal_qa_mode)
            finally:
                self._summaries_running.discard(mode)

        threading.Thread(target=run_summary, daemon=True).start()

    # 响应主动行为控制器的说话请求。
    def _handle_behavior_speak(self, text: str, duration_ms: int, action_name: str) -> None:
        """响应主动行为控制器的说话请求。"""
        if self._chat_in_progress() or self.chat_input.isVisible():
            return
        self.sprite_player.set_action(action_name)
        self._display_message(text, duration_ms, "proactive")

    # 接收场景问候请求，并按上下文决定本地或 API 生成。
    def _handle_scenario_greeting(self, payload: dict[str, Any]) -> None:
        """接收场景问候请求，并按上下文决定本地或 API 生成。"""
        if self._chat_in_progress() or self.chat_input.isVisible():
            return
        fallback_line = str(payload.get("fallback_line", "")).strip()
        if not self.deepseek_client.is_configured():
            self._pending_scenario_fallback_line = ""
            self._show_scenario_greeting_line(fallback_line)
            return
        if self.background_tasks.is_registered("chat"):
            return
        self._start_scenario_greeting_worker(payload)

    # 创建场景问候生成后台任务并绑定成功失败回调。
    def _start_scenario_greeting_worker(self, payload: dict[str, Any]) -> None:
        """创建场景问候生成后台任务并绑定成功失败回调。"""
        self.chat_thread = QThread(self)
        self._pending_scenario_fallback_line = str(payload.get("fallback_line", ""))
        self.chat_worker = ScenarioGreetingWorker(
            self.deepseek_client,
            context=payload.get("context", {}),
            fallback_line=self._pending_scenario_fallback_line,
            max_chars=int(payload.get("max_chars", 80) or 80),
        )
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(
            self._on_scenario_greeting_success,
            Qt.ConnectionType.QueuedConnection,
        )
        self.chat_worker.failed.connect(
            self._on_scenario_greeting_failure,
            Qt.ConnectionType.QueuedConnection,
        )
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        if not self._register_background_task(
            "chat",
            self.chat_thread,
            self.chat_worker,
            self._clear_chat_task_refs,
        ):
            self._pending_scenario_fallback_line = ""
            self._discard_unregistered_task(
                self.chat_thread,
                self.chat_worker,
                self._clear_chat_task_refs,
            )
            return
        self.chat_thread.start()

    # 展示模型生成的场景问候，并记录主动展示状态。
    @Slot(str)
    def _on_scenario_greeting_success(self, reply: str) -> None:
        """展示模型生成的场景问候，并记录主动展示状态。"""
        if self._closing_or_closed():
            return
        self._pending_scenario_fallback_line = ""
        self._show_scenario_greeting_line(reply)

    # 在场景问候生成失败时展示本地兜底台词。
    @Slot(str)
    def _on_scenario_greeting_failure(self, error_message: str) -> None:
        """在场景问候生成失败时展示本地兜底台词。"""
        logger.warning("Scenario greeting API failed; using local fallback: %s", error_message)
        if self._closing_or_closed():
            self._pending_scenario_fallback_line = ""
            return
        fallback = self._pending_scenario_fallback_line
        self._pending_scenario_fallback_line = ""
        if fallback:
            self._show_scenario_greeting_line(fallback)

    # 根据 line 显示场景问候台词内容并安排后续气泡状态。
    def _show_scenario_greeting_line(self, line: str) -> None:
        """根据 line 显示场景问候台词内容并安排后续气泡状态。"""
        if not line or self.chat_input.isVisible():
            return
        self.sprite_player.set_action("waving")
        self._display_message(
            line,
            self._proactive_greeting_duration_ms(),
            "proactive",
        )

    # 响应主动知识问候请求：基于 memory 调用 API 生成额外内容。
    def _handle_knowledge_speak(self) -> None:
        """响应主动知识问候请求：基于 memory 调用 API 生成额外内容。"""
        if self._chat_in_progress() or self.chat_input.isVisible():
            return

        if not self.deepseek_client.is_configured():
            # API 不可用时回退到本地主动说话
            self.behavior_controller.trigger_test_speak()
            return

        self.sprite_player.set_action("waving")
        self._start_knowledge_worker()

    # 创建后台线程执行记忆增强的知识问候 API 请求。
    def _start_knowledge_worker(self) -> None:
        """创建后台线程执行记忆增强的知识问候 API 请求。"""
        if self.background_tasks.is_registered("chat"):
            return

        memory = load_json(self.memory_path, {})
        self.chat_thread = QThread(self)
        self.chat_worker = KnowledgeSpeakWorker(
            self.deepseek_client,
            self.prompt_builder,
            memory,
            mem0_memory_service=self.mem0_memory_service,
            user_id=self._memory_user_id(),
            use_mem0=self.config_service.get_bool("memory.use_mem0_for_knowledge_speak", False),
            mem0_memory_context=self._pending_knowledge_mem0_context,
        )
        self._pending_knowledge_mem0_context = ""
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._on_knowledge_speak_success)
        self.chat_worker.failed.connect(self._on_knowledge_speak_failure)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        if not self._register_background_task(
            "chat",
            self.chat_thread,
            self.chat_worker,
            self._clear_chat_task_refs,
        ):
            self._discard_unregistered_task(
                self.chat_thread,
                self.chat_worker,
                self._clear_chat_task_refs,
            )
            return
        self.chat_thread.start()

    # 知识问候 API 成功返回后，展示内容并在右侧弹出可点击的应答气泡。
    def _on_knowledge_speak_success(self, reply: str) -> None:
        """知识问候 API 成功返回后，展示内容并在右侧弹出可点击的应答气泡。"""
        if self._closing_or_closed():
            return
        cleaned_reply = reply.strip() or "让我再看看哦。"
        self.sprite_player.set_action("idle")
        parts = split_knowledge_bubble_text(cleaned_reply)
        if len(parts) <= 1:
            self._display_message(parts[0] if parts else cleaned_reply, 15000, "proactive")
            self._show_knowledge_reply_ack()
            return

        self._display_message(parts[0], 7000, "proactive")
        QTimer.singleShot(5200, lambda second=parts[1]: self._show_knowledge_second_part(second))

    # 根据 text 显示知识问候secondpart内容并安排后续气泡状态。
    def _show_knowledge_second_part(self, text: str) -> None:
        """根据 text 显示知识问候secondpart内容并安排后续气泡状态。"""
        if self._closing_or_closed() or self.chat_input.isVisible():
            return
        self._display_message(text, 12000, "proactive")
        self._show_knowledge_reply_ack()

    # 显示知识问候回复ack内容并安排后续气泡状态。
    def _show_knowledge_reply_ack(self) -> None:
        """显示知识问候回复ack内容并安排后续气泡状态。"""
        ack = self.behavior_controller.pick_reply_ack_line()
        if ack:
            self.reply_bubble.set_always_on_top(
                self.config_service.get_bool("ui.always_on_top", True)
            )
            self.reply_bubble.show_message(ack, self.geometry(), 8000)
            self._sync_floating_widgets()

    # 知识问候 API 失败后展示错误提示。
    def _on_knowledge_speak_failure(self, error_message: str) -> None:
        """知识问候 API 失败后展示错误提示。"""
        if self._closing_or_closed():
            return
        self.sprite_player.set_action("failed")
        self._display_message(error_message, 8000, "assistant")

    # 用户点击右侧应答气泡，视为回应主动问候并更新间隔。
    def _handle_reply_bubble_clicked(self) -> None:
        """用户点击右侧应答气泡，视为回应主动问候并更新间隔。"""
        self.behavior_controller.notify_user_interaction()
        self.behavior_controller.notify_proactive_response()

    # 通过气泡组件显示一条消息。
    def _display_message(self, text: str, duration_ms: int, source: str = "system") -> None:
        """通过气泡组件显示一条消息。"""
        self.bubble.set_always_on_top(self.config_service.get_bool("ui.always_on_top", True))
        self.bubble.show_message(text, self.geometry(), duration_ms, source)
        self._sync_floating_widgets()

    # 聊天输入框打开后长时间未回复时，显示 waiting 话术并重启计时器。
    def _show_waiting_prompt(self) -> None:
        """聊天输入框打开后长时间未回复时，显示 waiting 话术并重启计时器。"""
        if not self.chat_input.isVisible():
            return
        reply = self.behavior_controller.pick_waiting_line()
        if reply:
            self._display_message(reply, 6000, "system")
        self._waiting_timer.start(25_000)

    # 根据当前模式决定用气泡还是正式问答面板展示回答。
    def _show_answer_output(self, text: str, source: str, question: str = "") -> None:
        """根据当前模式决定用气泡还是正式问答面板展示回答。"""
        if source == "assistant" and self._formal_qa_enabled():
            self._show_formal_answer_panel(question, text)
            return
        duration_ms = self._assistant_reply_bubble_duration_ms() if source == "assistant" else 9000
        self._display_message(text, duration_ms, source)

    # 按正式问答显示方式展示回答，支持新建面板或追加内容。
    def _show_formal_answer_panel(self, question: str, answer: str) -> None:
        """按正式问答显示方式展示回答，支持新建面板或追加内容。"""
        display_mode = self._formal_answer_display_mode()
        if (
            display_mode == "append"
            and self.active_formal_answer_panel is not None
            and self.active_formal_answer_panel.isVisible()
        ):
            self.active_formal_answer_panel.append_entry(question, answer)
            return

        panel = FormalAnswerPanel(title="正式问答")
        panel_id = id(panel)
        panel.destroyed.connect(
            lambda *_args, owned_panel_id=panel_id: self._on_formal_answer_panel_destroyed(
                owned_panel_id
            )
        )
        content = FormalAnswerPanel.format_entry(question, answer)
        panel.set_content("正式问答", content, self.geometry(), len(self.formal_answer_panels))
        self.formal_answer_panels.append(panel)
        self.active_formal_answer_panel = panel

    # 用正式面板承载较长的剪贴板处理结果，不创建聊天记录条目。
    def _show_clipboard_assistant_panel(self, mode: str, answer: str) -> None:
        """用正式面板承载较长的剪贴板处理结果，不创建聊天记录条目。"""
        label = CLIPBOARD_ASSISTANT_LABELS.get(mode, "处理结果")
        panel = FormalAnswerPanel(title="剪贴板助手")
        panel_id = id(panel)
        panel.destroyed.connect(
            lambda *_args, owned_panel_id=panel_id: self._on_formal_answer_panel_destroyed(
                owned_panel_id
            )
        )
        content = FormalAnswerPanel.format_entry(f"剪贴板{label}", answer)
        panel.set_content("剪贴板助手", content, self.geometry(), len(self.formal_answer_panels))
        self.formal_answer_panels.append(panel)
        self.active_formal_answer_panel = panel

    # 关闭并销毁所有正式问答面板。
    def _destroy_formal_answer_panels(self) -> None:
        """关闭并销毁所有正式问答面板。"""
        panels = list(self.formal_answer_panels)
        self.formal_answer_panels.clear()
        self.active_formal_answer_panel = None
        for panel in panels:
            panel.close()

    # 在正式问答面板销毁后移除引用，避免关闭后残留对象。
    def _on_formal_answer_panel_destroyed(self, panel_id: int) -> None:
        """在正式问答面板销毁后移除引用，避免关闭后残留对象。"""
        self.formal_answer_panels = [
            panel for panel in self.formal_answer_panels if id(panel) != panel_id
        ]
        if self.active_formal_answer_panel and id(self.active_formal_answer_panel) == panel_id:
            self.active_formal_answer_panel = (
                self.formal_answer_panels[-1] if self.formal_answer_panels else None
            )

    # 把最新精灵帧绘制到主窗口标签上。
    def _update_sprite(self, pixmap) -> None:
        """把最新精灵帧绘制到主窗口标签上。"""
        self.sprite_label.setPixmap(pixmap)
        self._resize_for_sprite()

    # 根据当前精灵帧尺寸同步调整窗口大小。
    def _resize_for_sprite(self) -> None:
        """根据当前精灵帧尺寸同步调整窗口大小。"""
        pixmap = self.sprite_label.pixmap()
        if not pixmap:
            return
        self.resize(pixmap.width(), pixmap.height())
        self.sprite_label.setGeometry(0, 0, pixmap.width(), pixmap.height())
        self._apply_sprite_window_mask(pixmap)
        self._sync_floating_widgets()

    # 按精灵帧的透明区域裁剪窗口，避免系统沿矩形外接框绘制边框。
    def _apply_sprite_window_mask(self, pixmap: QPixmap) -> None:
        """按精灵帧的透明区域裁剪窗口，避免系统沿矩形外接框绘制边框。"""
        mask = pixmap.mask()
        if mask.isNull():
            self.clearMask()
            self.sprite_label.clearMask()
            return
        self.setMask(mask)
        self.sprite_label.setMask(mask)

    # 恢复上次窗口位置；首次启动则放到屏幕右下角。
    def _restore_position(self) -> None:
        """恢复上次窗口位置；首次启动则放到屏幕右下角。"""
        position = self.window_position_service.restore_position(
            self.size(),
            self.sprite_player.base_size(),
            remember_last_position=self.config_service.get_bool("ui.remember_last_position", True),
        )
        self.move(position)

    # 保存当前窗口位置到本地状态文件。
    def _save_window_position(self) -> None:
        """保存当前窗口位置到本地状态文件。"""
        self.window_position_service.save_position(self.pos())

    # 判断窗口放在给定坐标后，是否至少有一部分仍位于某个屏幕可见区域内。
    def _position_visible_on_any_screen(self, position: QPoint) -> bool:
        """判断窗口放在给定坐标后，是否至少有一部分仍位于某个屏幕可见区域内。"""
        return self.window_position_service.position_visible_on_any_screen(
            position,
            self.size(),
        )

    # 在 Windows API 级别强制置顶主窗口，防止 WS_EX_TOPMOST 被系统清除。
    def _enforce_topmost(self) -> None:
        """在 Windows API 级别强制置顶主窗口，防止 WS_EX_TOPMOST 被系统清除。"""
        if not self.config_service.get_bool("ui.always_on_top", True):
            self._topmost_enforcement_timer.stop()
            return
        try:
            hwnd = int(self.winId())
            force_window_topmost(hwnd, True)
        except Exception:
            pass

    # 根据配置决定是否开启自主移动定时器。
    def _refresh_auto_move_timer(self) -> None:
        """根据配置决定是否开启自主移动定时器。"""
        if self.config_service.get_bool("ui.enable_free_move", False):
            self.auto_move_timer.start(random.randint(15_000, 28_000))
        else:
            self.auto_move_timer.stop()

    # 随机触发一次桌宠横向移动动画。
    def _trigger_auto_move(self) -> None:
        """随机触发一次桌宠横向移动动画。"""
        self._refresh_auto_move_timer()
        if self._chat_in_progress() or self._movement_locked():
            return
        screen = self._current_screen()
        if not screen:
            return
        available = screen.availableGeometry()
        current = self.pos()
        move_kind = random.choices(["left", "right", "jump"], weights=[4, 4, 2], k=1)[0]
        if move_kind == "jump":
            self._start_jump_auto_move(current, available)
            return

        delta = random.choice([-140, -100]) if move_kind == "left" else random.choice([100, 140])
        self._start_horizontal_move_test(delta, available=available)

    # 执行一次平滑的左右移动测试或自主移动。
    def _start_horizontal_move_test(self, delta_x: int, available: QRect | None = None) -> None:
        """执行一次平滑的左右移动测试或自主移动。"""
        if self._movement_locked():
            return

        if not available:
            screen = self._current_screen()
            if not screen:
                return
            available = screen.availableGeometry()

        self._stop_active_move_animation()
        current = self.pos()
        target_x = max(available.left(), min(current.x() + delta_x, available.right() - self.width()))
        target = QPoint(target_x, max(available.top(), min(current.y(), available.bottom() - self.height())))

        if target == current:
            return

        action = "running_right" if target.x() > current.x() else "running_left"
        self.sprite_player.set_action(action)
        self.move_animation = QPropertyAnimation(self, b"pos", self)
        self.move_animation.setDuration(1200)
        self.move_animation.setStartValue(current)
        self.move_animation.setEndValue(target)
        self.move_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.move_animation.finished.connect(self._finish_auto_move)
        self.move_animation.start()

    # 执行一次带 jumping 动作的自主跳跃。
    def _start_jump_auto_move(self, current: QPoint, available: QRect) -> None:
        """执行一次带 jumping 动作的自主跳跃。"""
        self._stop_active_move_animation()
        jump_height = max(24, self.height() // 2)
        peak_y = max(available.top(), current.y() - jump_height)
        peak = QPoint(current.x(), peak_y)

        self.sprite_player.set_action("jumping", fallback_action="idle", force_single_cycle=True)
        duration_ms = self.sprite_player.action_duration_ms("jumping", force_single_cycle=True)

        self.move_animation = QPropertyAnimation(self, b"pos", self)
        self.move_animation.setDuration(duration_ms)
        self.move_animation.setStartValue(current)
        self.move_animation.setKeyValueAt(0.5, peak)
        self.move_animation.setEndValue(current)
        self.move_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.move_animation.finished.connect(self._finish_auto_move)
        self.move_animation.start()

    # 在自主移动结束后恢复 idle 动作并保存位置。
    def _finish_auto_move(self) -> None:
        """在自主移动结束后恢复 idle 动作并保存位置。"""
        self.sprite_player.set_action("idle")
        self.move_animation = None
        self._save_window_position()
        self._sync_floating_widgets()

    # 停止当前移动动画并清空动画引用。
    def _stop_active_move_animation(self) -> None:
        """停止当前移动动画并清空动画引用。"""
        if self.move_animation and self.move_animation.state() == QPropertyAnimation.State.Running:
            self.move_animation.stop()
        self.move_animation = None

    # 判断当前窗口是否处于禁止自动移动的状态。
    def _movement_locked(self) -> bool:
        """判断当前窗口是否处于禁止自动移动的状态。"""
        return self.dragging or self.exit_animation_in_progress

    # 根据窗口当前位置查找所在屏幕，缺失时回退主屏幕。
    def _current_screen(self):
        """根据窗口当前位置查找所在屏幕，缺失时回退主屏幕。"""
        anchor_point = self.frameGeometry().center()
        screen = QApplication.screenAt(anchor_point)
        return screen or QApplication.primaryScreen()

    # 让气泡和输入框跟随角色当前位置，两个气泡互相避让。
    def _sync_floating_widgets(self) -> None:
        """让气泡和输入框跟随角色当前位置，两个气泡互相避让。"""
        anchor_rect = self.geometry()
        bubble_visible = self.bubble.isVisible()
        reply_visible = self.reply_bubble.isVisible()
        if bubble_visible:
            exclusions = [self.reply_bubble.geometry()] if reply_visible else None
            self.bubble.move(
                self.bubble_position_service.speech_bubble_position(
                    (self.bubble.width(), self.bubble.height()),
                    anchor_rect,
                    exclusions,
                )
            )
        if reply_visible:
            exclusions = [self.bubble.geometry()] if bubble_visible else None
            self.reply_bubble.move(
                self.bubble_position_service.reply_bubble_position(
                    (self.reply_bubble.width(), self.reply_bubble.height()),
                    anchor_rect,
                    exclusions,
                )
            )
        if self.chat_input.isVisible():
            self.chat_input.reposition(anchor_rect)

    # 判断当前是否仍有聊天请求在后台执行。
    def _chat_in_progress(self) -> bool:
        """判断当前是否仍有聊天请求在后台执行。"""
        return self.background_tasks.is_running("chat")

    # 判断是否正在后台整理并清空聊天记录。
    def _clear_history_in_progress(self) -> bool:
        """判断是否正在后台整理并清空聊天记录。"""
        return self.background_tasks.is_running("clear_history")

    # 检查后台任务注册表中是否仍有线程在运行。
    def _background_workers_running(self) -> bool:
        """检查后台任务注册表中是否仍有线程在运行。"""
        return self.background_tasks.any_running()

    # 请求所有后台任务退出，并返回仍未结束的任务名称。
    def _request_background_workers_quit(self) -> None:
        """请求所有后台任务退出，并返回仍未结束的任务名称。"""
        self.background_tasks.request_quit_all(timeout_ms=1000)

    # 请求后台任务退出，返回仍需等待自然结束的任务名。
    def _stop_background_workers(self) -> list[str]:
        """请求后台任务退出，返回仍需等待自然结束的任务名。"""
        return self.background_tasks.stop_all()

    # 在后台任务全部结束后继续执行被延迟的窗口关闭。
    def _maybe_close_after_workers_finished(self) -> None:
        """在后台任务全部结束后继续执行被延迟的窗口关闭。"""
        if not self._close_after_workers_finished:
            return
        if self._background_workers_running():
            return
        self._close_after_workers_finished = False
        QTimer.singleShot(0, self.close)

    # 判断当前用户聊天是否允许接入外部 API。
    def _api_chat_enabled(self) -> bool:
        """判断当前用户聊天是否允许接入外部 API。"""
        return self.config_service.get_bool("api.enable_chat_api", True)

    # 判断剪贴板助手功能是否启用，缺失配置时默认启用。
    def _clipboard_assistant_enabled(self) -> bool:
        """判断剪贴板助手功能是否启用，缺失配置时默认启用。"""
        return self.config_service.get_bool("clipboard.enabled", True)

    # 读取剪贴板文本最大处理字符数，异常配置回退到 4000。
    def _clipboard_max_chars(self) -> int:
        """读取剪贴板文本最大处理字符数，异常配置回退到 4000。"""
        return _positive_int(self.config_service.get("clipboard.max_chars", 4000), 4000)

    # 返回当前配置的聊天模型提供商。
    def _api_provider(self) -> str:
        """返回当前配置的聊天模型提供商。"""
        provider = self.config_service.get_str("api.provider", "deepseek").strip().lower()
        return "openai" if provider in {"openai", "gpt", "gpt_openai"} else "deepseek"

    # 判断当前是否开启正式问答模式。
    def _formal_qa_enabled(self) -> bool:
        """判断当前是否开启正式问答模式。"""
        return self.config_service.get_bool("chat.formal_qa_mode", False)

    # 读取正式问答多回答显示方式。
    def _formal_answer_display_mode(self) -> str:
        """读取正式问答多回答显示方式。"""
        mode = self.config_service.get_str("chat.formal_answer_display", "new_panel")
        return mode if mode in {"new_panel", "append"} else "new_panel"

    # 读取并返回当前 UI 缩放比例。
    def _ui_scale(self) -> float:
        """读取并返回当前 UI 缩放比例。"""
        try:
            return float(self.config_service.get("ui.scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0

    # 返回 UI 配置字典，不存在时自动补默认节点。
    def _ui_config(self) -> dict[str, Any]:
        """返回 UI 配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("ui", {})

    # 返回行为配置字典，不存在时自动补默认节点。
    def _behavior_config(self) -> dict[str, Any]:
        """返回行为配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("behavior", {})

    # 返回 API 配置字典，不存在时自动补默认节点。
    def _api_config(self) -> dict[str, Any]:
        """返回 API 配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("api", {})

    # 读取提醒功能开关，缺失时默认启用。
    def _reminders_enabled(self) -> bool:
        """读取提醒功能开关，缺失时默认启用。"""
        return self.config_service.get_bool("reminders.enabled", True)

    # 读取提醒轮询间隔，异常配置回退到 30 秒。
    def _reminder_check_interval_seconds(self) -> int:
        """读取提醒轮询间隔，异常配置回退到 30 秒。"""
        return _positive_int(self.config_service.get("reminders.check_interval_seconds", 30), 30)

    # 读取进行中提醒数量上限，异常配置回退到 20 条。
    def _max_active_reminders(self) -> int:
        """读取进行中提醒数量上限，异常配置回退到 20 条。"""
        return _positive_int(self.config_service.get("reminders.max_active_reminders", 20), 20)

    # 根据提醒和免打扰配置决定当前是否应投递提醒气泡。
    def _can_deliver_reminders(self) -> bool:
        """根据提醒和免打扰配置决定当前是否应投递提醒气泡。"""
        if not self.config_service.get_bool("reminders.respect_do_not_disturb", False):
            return True
        return not self.config_service.get_bool("behavior.do_not_disturb", False)

    # 返回聊天配置字典，不存在时自动补默认节点。
    def _chat_config(self) -> dict[str, Any]:
        """返回聊天配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("chat", {})

    # 读取配置片段，缺失时返回安全默认配置。
    def _memory_config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        return self.app_config.setdefault("memory", {})

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _memory_user_id(self) -> str:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
        return self.config_service.get_str("memory.mem0_user_id", "default_user")

    # 判断本地记忆中是否存在可用于知识问候的主题或偏好。
    def _has_knowledge_memory(self) -> bool | None:
        """判断本地记忆中是否存在可用于知识问候的主题或偏好。"""
        if not self.config_service.get_bool("memory.use_mem0_for_knowledge_speak", False):
            return False
        if self._pending_knowledge_mem0_context:
            return True
        if self.background_tasks.is_registered("mem0_init"):
            return None
        if self.background_tasks.is_registered("mem0_search"):
            return None
        if self.mem0_memory_service is None or not self.mem0_memory_service.is_available():
            return False
        self._start_mem0_search_worker()
        return None

    # 读取助手回复气泡展示时长，配置无效时使用默认毫秒数。
    def _assistant_reply_bubble_duration_ms(self) -> int:
        """读取助手回复气泡展示时长，配置无效时使用默认毫秒数。"""
        value = self.config_service.get_int("ui.bubble_durations_ms.assistant_reply", 15000)
        return value if value > 0 else 15000

    # 读取主动问候气泡展示时长，配置无效时使用默认毫秒数。
    def _proactive_greeting_duration_ms(self) -> int:
        """读取主动问候气泡展示时长，配置无效时使用默认毫秒数。"""
        value = self.config_service.get_int("ui.bubble_durations_ms.proactive_greeting", 6000)
        return value if value > 0 else 6000

    # 同步聊天流程控制器的待处理状态到窗口字段。
    def _sync_chat_flow_state(self) -> None:
        """同步聊天流程控制器的待处理状态到窗口字段。"""
        self.pending_formal_question = self.chat_flow_controller.pending_question
        self._pending_was_formal = self.chat_flow_controller.pending_was_formal

    # 返回当前模式对应的聊天存储实例。
    def _active_chat_store(self) -> ChatStore:
        """返回当前模式对应的聊天存储实例。"""
        return self.chat_flow_controller.active_store()

    # 返回当前内存中的配置快照。
    def _config_snapshot(self) -> dict[str, Any]:
        """返回当前内存中的配置快照。"""
        return self.app_config

    # 优先读取 app_config.json，缺失时回退到 app_config.example.json。
    def _load_app_config(self) -> dict[str, Any]:
        """优先读取 app_config.json，缺失时回退到 app_config.example.json。"""
        return load_json_prefer_primary(self.config_path, self.example_config_path, {})

    # 把当前内存配置写回配置文件。
    def _save_app_config(self) -> None:
        """把当前内存配置写回配置文件。"""
        save_json(self.config_path, self.app_config)
