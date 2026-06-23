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

    def with_kind(self, kind: ChatDecisionKind) -> ChatFlowDecision:
        """处理 `with_kind` 对应的业务逻辑。"""
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
        "我已经收到你说的话啦。先在 config/app_config.json 里填好 DeepSeek API key，"
        "或者先关闭“聊天接入 API”。"
    )

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

    def can_start_chat(self, chat_task_registered: bool) -> bool:
        """判断 `can_start_chat` 对应的条件是否成立。"""
        return not chat_task_registered

    def begin_user_message(self, message: str) -> ChatMessageContext:
        """处理 `begin_user_message` 对应的业务逻辑。"""
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

    def append_assistant_reply(
        self,
        context: ChatMessageContext,
        reply: str,
    ) -> ChatFlowDecision:
        """添加 `append_assistant_reply` 对应的内容。"""
        context.store.append_message("assistant", reply)
        return ChatFlowDecision(
            kind="local_reply",
            message=context.message,
            formal_qa_mode=context.formal_qa_mode,
            question=context.question,
            reply=reply,
        )

    def decide_after_thinking(self, context: ChatMessageContext) -> ChatFlowDecision:
        """处理 `decide_after_thinking` 对应的业务逻辑。"""
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

    def chat_worker_kwargs(
        self,
        message: str,
        client: Any,
        prompt_builder: Any,
        context_manager: Any,
        mem0_memory_service: Any,
        user_id: str,
        app_config: dict[str, Any],
    ) -> dict[str, Any]:
        """处理 `chat_worker_kwargs` 对应的业务逻辑。"""
        return {
            "user_message": message,
            "client": client,
            "prompt_builder": prompt_builder,
            "context_manager": context_manager,
            "formal_qa_mode": self.pending_was_formal,
            "mem0_memory_service": mem0_memory_service,
            "user_id": user_id,
            "app_config": app_config,
        }

    def complete_success(self, reply: str) -> ChatCompletion:
        """处理 `complete_success` 对应的业务逻辑。"""
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

    def complete_failure(self, error_message: str) -> ChatFailure:
        """处理 `complete_failure` 对应的业务逻辑。"""
        failure = ChatFailure(
            error_message=error_message,
            question=self.pending_question,
            formal_qa_mode=self.pending_was_formal,
        )
        self.pending_question = ""
        self.pending_was_formal = False
        return failure

    def active_store(self) -> Any:
        """处理 `active_store` 对应的业务逻辑。"""
        return self._store_for_mode(self._formal_qa_enabled())

    def _store_for_mode(self, formal_qa_mode: bool) -> Any:
        """保存 `_store_for_mode` 产生的数据。"""
        return self.formal_store if formal_qa_mode else self.informal_store
