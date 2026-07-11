from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.desktop_pet_window import KnowledgeSpeakWorker  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402


class FakeClient:
    # 返回固定知识问候文本，避免测试访问网络。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """返回固定知识问候文本。"""
        return "这是一条知识问候。"


class FakePromptBuilder:
    # 保存知识问候构造的提示词，供断言读取是否使用真实描述文本。
    def __init__(self) -> None:
        """初始化提示词记录容器。"""
        self.prompts: list[str] = []
        self.options: list[dict] = []

    def build_messages(self, prompt: str, *args, **kwargs) -> list[dict[str, str]]:
        """记录提示词并返回最小消息列表。"""
        self.prompts.append(prompt)
        self.options.append(kwargs)
        return [{"role": "user", "content": prompt}]


class KnowledgeSpeakMemoryTests(unittest.TestCase):
    # 准备独立的长期记忆文件。
    def setUp(self) -> None:
        """准备独立的长期记忆文件。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_knowledge_speak_memory" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # 清理测试生成的临时数据。
    def tearDown(self) -> None:
        """清理测试生成的临时数据。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证正式模式读取摘要写入的编号记录并使用正式提示词。
    def test_formal_mode_reads_descriptions_written_by_memory_summary_operations(self) -> None:
        """验证正式知识问候不再把编号记录字典当作列表。"""
        store = MemoryStore(self.temp_dir / "memory.json")
        store.apply_summary_operations(
            "informal",
            3,
            [
                {
                    "action": "add",
                    "field": "user_profile.preferences",
                    "description": ["喜欢简洁、可执行的建议"],
                },
                {
                    "action": "add",
                    "field": "work_study.current_learning_topics",
                    "description": ["Python 异步编程"],
                },
                {
                    "action": "add",
                    "field": "work_study.current_projects",
                    "description": ["桌宠记忆整理"],
                },
            ],
        )
        prompt_builder = FakePromptBuilder()
        worker = KnowledgeSpeakWorker(
            FakeClient(),  # type: ignore[arg-type]
            prompt_builder,  # type: ignore[arg-type]
            store.load(),
            formal_qa_mode=True,
        )
        replies: list[str] = []
        errors: list[str] = []
        worker.finished.connect(replies.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(replies, ["这是一条知识问候。"])
        prompt = prompt_builder.prompts[0]
        self.assertIn("喜欢简洁、可执行的建议", prompt)
        self.assertIn("Python 异步编程", prompt)
        self.assertIn("桌宠记忆整理", prompt)
        self.assertNotIn("preferences_1", prompt)
        self.assertTrue(prompt_builder.options[0]["formal_qa_mode"])
        self.assertIn("正式问答模式", prompt)

    # 验证非正式模式只使用个人备注生成轻柔陪伴内容。
    def test_informal_mode_uses_personal_notes_for_gentle_companionship(self) -> None:
        """验证非正式知识问候读取个人备注且不走正式知识提示词。"""
        store = MemoryStore(self.temp_dir / "memory.json")
        store.apply_summary_operations(
            "informal",
            3,
            [
                {
                    "action": "add",
                    "field": "user_profile.important_personal_notes",
                    "description": ["最近事情很多，感觉有些累"],
                },
                {
                    "action": "add",
                    "field": "work_study.current_learning_topics",
                    "description": ["不应作为非正式问候主题"],
                },
            ],
        )
        prompt_builder = FakePromptBuilder()
        worker = KnowledgeSpeakWorker(
            FakeClient(),  # type: ignore[arg-type]
            prompt_builder,  # type: ignore[arg-type]
            store.load(),
            formal_qa_mode=False,
        )
        replies: list[str] = []
        worker.finished.connect(replies.append)

        worker.run()

        self.assertEqual(replies, ["这是一条知识问候。"])
        prompt = prompt_builder.prompts[0]
        self.assertIn("最近事情很多，感觉有些累", prompt)
        self.assertNotIn("不应作为非正式问候主题", prompt)
        self.assertIn("不要提及记忆", prompt)
        self.assertNotIn("硬性知识", prompt)
        self.assertFalse(prompt_builder.options[0]["formal_qa_mode"])

    # 验证轻松兴趣优先于个人备注，互动字段只作为表达约束。
    def test_informal_mode_prefers_light_topic_and_uses_style_hints(self) -> None:
        """验证非正式知识问候优先轻松话题并读取互动边界。"""
        store = MemoryStore(self.temp_dir / "memory.json")
        store.apply_summary_operations(
            "informal",
            3,
            [
                {
                    "action": "add",
                    "field": "user_profile.light_interests",
                    "description": ["像素风游戏"],
                },
                {
                    "action": "add",
                    "field": "user_profile.comfort_preferences",
                    "description": ["喜欢简短、不催促的陪伴"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.interaction_patterns.recent_positive_events",
                    "description": ["今天完成了一件小事"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.companionship_style.encouragement_style",
                    "description": ["具体且低压力"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.companionship_style.addressing_preference",
                    "description": ["自然称呼"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.companionship_style.proactive_boundary",
                    "description": ["忙碌时低频出现"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.interaction_patterns.recent_interaction_mode",
                    "description": ["最近偏忙"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.interaction_patterns.response_to_proactive_greetings",
                    "description": ["不需要频繁追问"],
                },
                {
                    "action": "add",
                    "field": "user_profile.important_personal_notes",
                    "description": ["不应成为优先话题的个人备注"],
                },
            ],
        )
        prompt_builder = FakePromptBuilder()
        worker = KnowledgeSpeakWorker(
            FakeClient(),  # type: ignore[arg-type]
            prompt_builder,  # type: ignore[arg-type]
            store.load(),
            formal_qa_mode=False,
        )

        worker.run()

        prompt = prompt_builder.prompts[0]
        self.assertTrue("像素风游戏" in prompt or "今天完成了一件小事" in prompt)
        self.assertNotIn("不应成为优先话题的个人备注", prompt)
        for value in (
            "喜欢简短、不催促的陪伴",
            "具体且低压力",
            "自然称呼",
            "忙碌时低频出现",
            "最近偏忙",
            "不需要频繁追问",
        ):
            self.assertIn(value, prompt)


if __name__ == "__main__":
    unittest.main()
