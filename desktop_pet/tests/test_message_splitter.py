from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.message_splitter import split_knowledge_bubble_text  # noqa: E402


class MessageSplitterTests(unittest.TestCase):
    def test_splits_on_chinese_period_into_two_parts(self) -> None:
        text = "间隔重复比连续复习更容易形成长期记忆。今天学完后，明天和三天后再看一遍会更稳。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "间隔重复比连续复习更容易形成长期记忆。",
                "今天学完后，明天和三天后再看一遍会更稳。",
            ],
        )

    def test_short_first_sentence_is_merged_with_next_sentence(self) -> None:
        text = "你知道吗。间隔重复很有用。把复习分散到几天里，通常比一天内反复看更稳。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "你知道吗。间隔重复很有用。",
                "把复习分散到几天里，通常比一天内反复看更稳。",
            ],
        )

    def test_keeps_single_sentence_whole(self) -> None:
        text = "这个知识点可以先记成一个简单规则，再慢慢补细节"

        self.assertEqual(split_knowledge_bubble_text(text), [text])

    def test_supports_question_and_exclamation_marks(self) -> None:
        text = "为什么分散复习更稳？因为大脑需要间隔来重新提取信息！这个过程会加深记忆。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "为什么分散复习更稳？",
                "因为大脑需要间隔来重新提取信息！这个过程会加深记忆。",
            ],
        )

    def test_normalizes_whitespace(self) -> None:
        text = "第一段内容足够长。\n\n第二句。"

        self.assertEqual(split_knowledge_bubble_text(text), ["第一段内容足够长。", "第二句。"])


if __name__ == "__main__":
    unittest.main()
