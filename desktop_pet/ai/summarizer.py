from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.context_budget import clip_text, read_context_budget
from ai.deepseek_client import DeepSeekClient, DeepSeekError
from storage.chat_store import ChatStore
from storage.json_store import load_json, load_json_prefer_primary, save_json
from storage.path_lock import lock_for_path
from utils.log_sanitizer import safe_exception
from utils.logger import get_logger
from utils.time_utils import utc_iso


logger = get_logger(__name__)

DEFAULT_SUMMARY = {
    "summary": "",
    "highlights": [],
    "last_updated": "",
    "summaries": [],
}


@dataclass(frozen=True)
class SummaryResult:
    """单次模式摘要的归档结果。"""

    mode: str
    sequence: int
    snapshot: list[dict[str, Any]]
    trigger_source: str


class Summarizer:
    # 初始化摘要器，关联摘要文件、聊天记录和模型客户端。
    def __init__(
        self,
        summary_path: str | Path,
        chat_store: ChatStore,
        deepseek_client: DeepSeekClient,
        config_path: str | Path | None = None,
        fallback_config_path: str | Path | None = None,
    ) -> None:
        """初始化摘要器，关联摘要文件、聊天记录和模型客户端。"""
        self.summary_path = Path(summary_path)
        self.chat_store = chat_store
        self.deepseek_client = deepseek_client
        self.config_path = Path(config_path) if config_path else None
        self.fallback_config_path = (
            Path(fallback_config_path) if fallback_config_path else self.config_path
        )
        self._summary_lock = lock_for_path(self.summary_path)

    # 读取当前对话摘要数据。
    def load_summary(self) -> dict[str, Any]:
        """读取当前对话摘要数据。"""
        with self._summary_lock:
            payload = load_json(self.summary_path, DEFAULT_SUMMARY)
            normalized, changed = self._normalize_archive(payload)
            if changed:
                save_json(self.summary_path, normalized)
            return normalized

    # 在达到轮数阈值或强制触发时尝试生成并保存摘要。
    def maybe_summarize(
        self,
        trigger_rounds: int,
        force: bool = False,
        trigger_source: str = "round_threshold",
    ) -> SummaryResult | None:
        """在达到轮数阈值或强制触发时尝试生成并保存摘要。"""
        with self._summary_lock:
            history = self.chat_store.all_messages()
            if not self._has_summarizable_history(history):
                logger.info("Skip summary because chat history has no user content")
                return None

            current_summary, migrated = self._normalize_archive(
                load_json(self.summary_path, DEFAULT_SUMMARY)
            )
            if not force and not self._should_summarize(history, trigger_rounds):
                if migrated:
                    save_json(self.summary_path, current_summary)
                return None

            try:
                payload = self._summarize_history(history)
            except Exception as exc:  # noqa: BLE001
                logger.error("Summary generation failed: %s", safe_exception(exc))
                return None

            sequence = len(current_summary["summaries"]) + 1
            created_at = utc_iso()
            entry = {
                "sequence": sequence,
                "summary": str(payload.get("summary", "")).strip(),
                "highlights": self._string_list(payload.get("highlights", []))[:3],
                "created_at": created_at,
                "trigger_source": str(trigger_source or "round_threshold"),
            }
            current_summary["summaries"].append(entry)
            current_summary["summary"] = entry["summary"]
            current_summary["highlights"] = entry["highlights"]
            current_summary["last_updated"] = created_at
            save_json(self.summary_path, current_summary)
            return SummaryResult(
                mode=str(getattr(self.chat_store, "mode", "unknown")),
                sequence=sequence,
                snapshot=history,
                trigger_source=entry["trigger_source"],
            )

    # 返回当前模式最近若干条归档摘要，供记忆总结使用。
    def recent_summary_entries(self, limit: int = 3) -> list[dict[str, Any]]:
        """返回当前模式最近若干条归档摘要。"""
        summaries = self.load_summary().get("summaries", [])
        count = max(0, int(limit))
        if not isinstance(summaries, list) or count == 0:
            return []
        return [dict(item) for item in summaries[-count:] if isinstance(item, dict)]

    # 兼容旧版单摘要文件并规范化为追加式归档载荷。
    @staticmethod
    def _normalize_archive(payload: Any) -> tuple[dict[str, Any], bool]:
        """兼容旧版单摘要文件并规范化为追加式归档载荷。"""
        source = payload if isinstance(payload, dict) else {}
        raw_summaries = source.get("summaries", [])
        changed = not isinstance(raw_summaries, list)
        entries: list[dict[str, Any]] = []
        if isinstance(raw_summaries, list):
            for raw in raw_summaries:
                if not isinstance(raw, dict):
                    changed = True
                    continue
                text = str(raw.get("summary", "")).strip()
                highlights = raw.get("highlights", [])
                if not text and not highlights and not (
                    "sequence" in raw or "created_at" in raw or "trigger_source" in raw
                ):
                    changed = True
                    continue
                entries.append(
                    {
                        "sequence": len(entries) + 1,
                        "summary": text,
                        "highlights": [str(item).strip() for item in highlights if str(item).strip()][:3]
                        if isinstance(highlights, list)
                        else [],
                        "created_at": str(raw.get("created_at", raw.get("last_updated", ""))).strip(),
                        "trigger_source": str(raw.get("trigger_source", "legacy")).strip() or "legacy",
                    }
                )
        if not entries:
            legacy_text = str(source.get("summary", "")).strip()
            legacy_highlights = source.get("highlights", [])
            if legacy_text or legacy_highlights:
                entries.append(
                    {
                        "sequence": 1,
                        "summary": legacy_text,
                        "highlights": [str(item).strip() for item in legacy_highlights if str(item).strip()][:3]
                        if isinstance(legacy_highlights, list)
                        else [],
                        "created_at": str(source.get("last_updated", "")).strip(),
                        "trigger_source": "legacy",
                    }
                )
                changed = True
        latest = entries[-1] if entries else {}
        normalized = {
            "summary": str(latest.get("summary", "")),
            "highlights": list(latest.get("highlights", [])),
            "last_updated": str(source.get("last_updated", latest.get("created_at", ""))),
            "summaries": entries,
        }
        return normalized, changed or source != normalized

    # 读取配置片段，缺失时返回安全默认配置。
    def _config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        if self.config_path is None:
            return {}
        fallback = self.fallback_config_path or self.config_path
        return load_json_prefer_primary(self.config_path, fallback, {})

    # 读取预算配置，返回当前流程使用的限制值。
    def _budget(self) -> dict[str, int]:
        """读取预算配置，返回当前流程使用的限制值。"""
        return read_context_budget(self._config())

    # 根据当前剩余 history 和 trigger_rounds 判断是否需要生成摘要。
    def _should_summarize(
        self,
        history: list[dict[str, Any]],
        trigger_rounds: int,
    ) -> bool:
        """根据当前剩余 history 和 trigger_rounds 判断是否需要生成摘要。"""
        trigger_rounds = max(1, int(trigger_rounds))
        total_user_rounds = self._count_user_messages(history)
        if total_user_rounds < trigger_rounds:
            return False
        return total_user_rounds >= trigger_rounds

    # 统计历史消息中的用户发言数量。
    def _count_user_messages(self, history: list[dict[str, Any]]) -> int:
        """统计历史消息中的用户发言数量。"""
        return len([item for item in history if item.get("role") == "user"])

    # 只有存在非空用户消息时才允许生成摘要。
    def _has_summarizable_history(self, history: list[dict[str, Any]]) -> bool:
        """只有存在非空用户消息时才允许生成摘要。"""
        return any(
            item.get("role") == "user" and str(item.get("content", "")).strip()
            for item in history
        )

    # 根据 history 压缩聊天历史，生成摘要内容。
    def _summarize_history(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """根据 history 压缩聊天历史，生成摘要内容。"""
        if not self.deepseek_client.is_configured():
            return self._local_summary(history)

        summary_payload = self._model_summary(history)
        if summary_payload is None:
            return self._local_summary(history)

        return summary_payload

    # 根据 history 请求模型生成摘要 JSON，失败时交给本地兜底。
    def _model_summary(self, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        """根据 history 请求模型生成摘要 JSON，失败时交给本地兜底。"""
        try:
            content = self.deepseek_client.chat(self._summary_messages(history))
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                budget = self._budget()
                return {
                    "summary": clip_text(str(parsed.get("summary", "")).strip(), budget["max_summary_chars"]),
                    "highlights": [
                        clip_text(item, 120)
                        for item in self._string_list(parsed.get("highlights", []))[:3]
                    ],
                }
        except (DeepSeekError, json.JSONDecodeError) as exc:
            logger.warning("Falling back to local summary after model failure: %s", safe_exception(exc))
        return None

    # 从最近对话构建模型摘要输入，保留角色信息以便模型区分用户和助手发言。
    def _summary_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """从最近对话构建模型摘要输入，保留角色信息以便模型区分用户和助手发言。"""
        transcript = self._build_transcript(
            history,
            char_budget=self._budget()["summary_max_input_chars"],
        )
        return [
            {
                "role": "system",
                "content": (
                    "请把以下对话总结成 JSON，不要输出 JSON 之外的任何内容。"
                    "这一轮只负责生成对话摘要和高光，不要提取用户记忆。"
                    '格式必须是：{"summary":"","highlights":[""]}'
                ),
            },
            {"role": "user", "content": transcript},
        ]

    # 在没有模型可用时，根据最近对话生成简化本地摘要。
    def _local_summary(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """在没有模型可用时，根据最近对话生成简化本地摘要。"""
        budget = self._budget()
        recent = self._cap_messages(history, budget["summary_max_input_chars"])
        summary_lines = [
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in recent if item.get("content")
        ]
        summary = " | ".join(summary_lines[-6:])
        return {
            "summary": clip_text(summary, budget["max_summary_chars"]),
            "highlights": [clip_text(item.get("content", ""), 80) for item in recent[-3:]],
        }

    # 根据 history、char_budget 组装对话转录文本并返回给调用方。
    def _build_transcript(
        self,
        history: list[dict[str, Any]],
        char_budget: int,
    ) -> str:
        """根据 history、char_budget 组装对话转录文本并返回给调用方。"""
        messages = self._cap_messages(history, char_budget)
        lines: list[str] = []
        for item in messages:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{item.get('role', 'user')}: {content}")
        return clip_text("\n".join(lines), char_budget)

    # 根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。
    def _cap_messages(self, history: list[dict[str, Any]], char_budget: int) -> list[dict[str, Any]]:
        """根据 history、char_budget 限制消息数量和长度，返回符合预算的消息列表。"""
        kept: list[dict[str, Any]] = []
        used = 0
        per_message_limit = self._budget()["max_history_message_chars"]
        for item in reversed(history):
            content = clip_text(item.get("content", ""), per_message_limit)
            if not content:
                continue
            role = str(item.get("role", "user"))
            line = f"{role}: {content}"
            if used + len(line) > char_budget:
                remaining = char_budget - used
                if remaining > len(role) + 10:
                    clipped = clip_text(content, max(1, remaining - len(role) - 2))
                    if clipped:
                        kept.append({**item, "content": clipped})
                break
            kept.append({**item, "content": content})
            used += len(line)
        kept.reverse()
        return kept

    # 将任意输入标准化为去重的非空字符串列表。
    def _string_list(self, value: Any) -> list[str]:
        """将任意输入标准化为去重的非空字符串列表。"""
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(clip_text(text, 120))
        return normalized
