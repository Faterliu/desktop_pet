from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.desktop_pet_window import ScenarioGreetingWorker  # noqa: E402


class FakeScenarioClient:
    # 初始化当前对象及其依赖。
    def __init__(self, reply: str) -> None:
        """初始化当前对象及其依赖。"""
        self.reply = reply
        self.messages: list[dict[str, str]] = []

    # 为 FakeScenarioClient 测试替身提供聊天行为。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """为 FakeScenarioClient 测试替身提供聊天行为。"""
        self.messages = messages
        return self.reply


class ScenarioGreetingWorkerTests(unittest.TestCase):
    # 验证工作线程 uses 兜底 when model exposes 记忆 language场景下的预期结果。
    def test_worker_uses_fallback_when_model_exposes_memory_language(self) -> None:
        """验证工作线程 uses 兜底 when model exposes 记忆 language场景下的预期结果。"""
        client = FakeScenarioClient("根据记忆，你最近在做桌宠记忆系统。")
        worker = ScenarioGreetingWorker(
            client,  # type: ignore[arg-type]
            context={"recent_task_focus": ["桌宠记忆系统"]},
            fallback_line="桌宠记忆系统这块先抓最关键的一小步就行。",
            max_chars=80,
        )
        results: list[str] = []
        worker.finished.connect(lambda text: results.append(text))

        worker.run()

        self.assertEqual(results, ["桌宠记忆系统这块先抓最关键的一小步就行。"])
        prompt = "\n".join(item["content"] for item in client.messages)
        self.assertIn("不要说“根据记忆”", prompt)

    # 验证工作线程 sanitizes length场景下的预期结果。
    def test_worker_sanitizes_length(self) -> None:
        """验证工作线程 sanitizes length场景下的预期结果。"""
        client = FakeScenarioClient("桌宠记忆系统这块可以先从 Prompt 分区和回退路径开始整理。")
        worker = ScenarioGreetingWorker(
            client,  # type: ignore[arg-type]
            context={"recent_task_focus": ["桌宠记忆系统"]},
            fallback_line="桌宠记忆系统这块先抓最关键的一小步就行。",
            max_chars=20,
        )
        results: list[str] = []
        worker.finished.connect(lambda text: results.append(text))

        worker.run()

        self.assertLessEqual(len(results[0]), 20)


if __name__ == "__main__":
    unittest.main()
