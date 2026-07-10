from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal


ChatDecisionKind = Literal["local_reply", "missing_api_config", "start_api"]


@dataclass(frozen=True)
class ChatMessageContext:
    message: str
    formal_qa_mode: bool
    question: str
    store: Any


@dataclass(frozen=True)
class ChatFlowDecision:
    kind: ChatDecisionKind
    message: str
    formal_qa_mode: bool
    question: str = ""
    reply: str = ""

    # 复制聊天结果上下文并写入新的结果类型。
    def with_kind(self, kind: ChatDecisionKind) -> ChatFlowDecision:
        """复制聊天结果上下文并写入新的结果类型。"""
        return ChatFlowDecision(
            kind=kind,
            message=self.message,
            formal_qa_mode=self.formal_qa_mode,
            question=self.question,
            reply=self.reply,
        )


@dataclass(frozen=True)
class ChatCompletion:
    reply: str
    question: str
    formal_qa_mode: bool


@dataclass(frozen=True)
class ChatFailure:
    error_message: str
    question: str
    formal_qa_mode: bool


class ChatFlowController:
    """协调主聊天流程中的非界面状态变化。"""

    missing_api_reply = (
        "我已经收到你说的话啦。先在 config/app_config.json 里填好当前模型提供商的 API key，"
        "或者先关闭“聊天接入 API”。"
    )

    # 初始化当前对象及其依赖。
    def __init__(
        self,
        formal_store: Any,
        informal_store: Any,
        formal_qa_enabled: Callable[[], bool],
        api_chat_enabled: Callable[[], bool],
        api_configured: Callable[[], bool],
        local_reply_provider: Callable[[str, bool], str],
    ) -> None:
        """初始化当前对象及其依赖。"""
        self.formal_store = formal_store
        self.informal_store = informal_store
        self._formal_qa_enabled = formal_qa_enabled
        self._api_chat_enabled = api_chat_enabled
        self._api_configured = api_configured
        self._local_reply_provider = local_reply_provider
        self.pending_question = ""
        self.pending_was_formal = False

    # 根据任务注册表判断指定聊天任务能否开始。
    def can_start_chat(self, chat_task_registered: bool) -> bool:
        """根据任务注册表判断指定聊天任务能否开始。"""
        return not chat_task_registered

    # 根据 message 处理聊天消息流程，更新上下文和展示状态。
    def begin_user_message(self, message: str) -> ChatMessageContext:
        """根据 message 处理聊天消息流程，更新上下文和展示状态。"""
        formal_qa_mode = self._formal_qa_enabled()
        store = self._store_for_mode(formal_qa_mode)
        store.append_message("user", message)
        self.pending_was_formal = formal_qa_mode
        self.pending_question = message if formal_qa_mode else ""
        return ChatMessageContext(
            message=message,
            formal_qa_mode=formal_qa_mode,
            question=self.pending_question,
            store=store,
        )

    # 把助手回复追加到当前聊天存储，并写入待处理上下文。
    def append_assistant_reply(
        self,
        context: ChatMessageContext,
        reply: str,
    ) -> ChatFlowDecision:
        """把助手回复追加到当前聊天存储，并写入待处理上下文。"""
        context.store.append_message("assistant", reply)
        return ChatFlowDecision(
            kind="local_reply",
            message=context.message,
            formal_qa_mode=context.formal_qa_mode,
            question=context.question,
            reply=reply,
        )

    # 根据 context 整理decide after thinking，并把结果交给调用方或写回状态。
    def decide_after_thinking(self, context: ChatMessageContext) -> ChatFlowDecision:
        """根据 context 整理decide after thinking，并把结果交给调用方或写回状态。"""
        if not self._api_chat_enabled():
            reply = self._local_reply_provider(context.message, context.formal_qa_mode)
            return self.append_assistant_reply(context, reply)

        if not self._api_configured():
            return self.append_assistant_reply(
                context,
                self.missing_api_reply,
            ).with_kind("missing_api_config")

        return ChatFlowDecision(
            kind="start_api",
            message=context.message,
            formal_qa_mode=context.formal_qa_mode,
            question=context.question,
        )

    # 根据 message、client、prompt_builder 处理聊天消息流程，更新上下文和展示状态。
    def chat_worker_kwargs(
        self,
        message: str,
        client: Any,
        prompt_builder: Any,
        context_manager: Any,
        mem0_memory_service: Any,
        user_id: str,
        app_config: dict[str, Any],
        reminder_tool: Any = None,
    ) -> dict[str, Any]:
        """根据 message、client、prompt_builder 处理聊天消息流程，更新上下文和展示状态。"""
        return {
            "user_message": message,
            "client": client,
            "prompt_builder": prompt_builder,
            "context_manager": context_manager,
            "formal_qa_mode": self.pending_was_formal,
            "mem0_memory_service": mem0_memory_service,
            "user_id": user_id,
            "app_config": app_config,
            "reminder_tool": reminder_tool,
        }

    # 保存助手回复，清理待处理上下文并返回本轮聊天结果。
    def complete_success(self, reply: str) -> ChatCompletion:
        """保存助手回复，清理待处理上下文并返回本轮聊天结果。"""
        cleaned_reply = reply.strip() or "我在这里哦。"
        store = self._store_for_mode(self.pending_was_formal)
        store.append_message("assistant", cleaned_reply)
        completion = ChatCompletion(
            reply=cleaned_reply,
            question=self.pending_question,
            formal_qa_mode=self.pending_was_formal,
        )
        self.pending_question = ""
        self.pending_was_formal = False
        return completion

    # 记录聊天失败信息，清理待处理上下文并返回错误展示内容。
    def complete_failure(self, error_message: str) -> ChatFailure:
        """记录聊天失败信息，清理待处理上下文并返回错误展示内容。"""
        failure = ChatFailure(
            error_message=error_message,
            question=self.pending_question,
            formal_qa_mode=self.pending_was_formal,
        )
        self.pending_question = ""
        self.pending_was_formal = False
        return failure

    # 返回当前正式或非正式聊天模式对应的消息存储。
    def active_store(self) -> Any:
        """返回当前正式或非正式聊天模式对应的消息存储。"""
        return self._store_for_mode(self._formal_qa_enabled())

    # 根据正式问答模式返回对应聊天存储。
    def _store_for_mode(self, formal_qa_mode: bool) -> Any:
        """根据正式问答模式返回对应聊天存储。"""
        return self.formal_store if formal_qa_mode else self.informal_store
