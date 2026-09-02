from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.message_splitter import (  # noqa: E402
    split_informal_answer_text,
    split_knowledge_bubble_text,
)


class MessageSplitterTests(unittest.TestCase):
    # 验证splits on chinese period into two parts场景下的预期结果。
    def test_splits_on_chinese_period_into_two_parts(self) -> None:
        """验证splits on chinese period into two parts场景下的预期结果。"""
        text = "间隔重复比连续复习更容易形成长期记忆。今天学完后，明天和三天后再看一遍会更稳。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "间隔重复比连续复习更容易形成长期记忆。",
                "今天学完后，明天和三天后再看一遍会更稳。",
            ],
        )

    # 验证short first sentence is merged with next sentence场景下的预期结果。
    def test_short_first_sentence_is_merged_with_next_sentence(self) -> None:
        """验证short first sentence is merged with next sentence场景下的预期结果。"""
        text = "你知道吗。间隔重复很有用。把复习分散到几天里，通常比一天内反复看更稳。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "你知道吗。间隔重复很有用。",
                "把复习分散到几天里，通常比一天内反复看更稳。",
            ],
        )

    # 验证keeps single sentence whole场景下的预期结果。
    def test_keeps_single_sentence_whole(self) -> None:
        """验证keeps single sentence whole场景下的预期结果。"""
        text = "这个知识点可以先记成一个简单规则，再慢慢补细节"

        self.assertEqual(split_knowledge_bubble_text(text), [text])

    # 验证supports question and exclamation marks场景下的预期结果。
    def test_supports_question_and_exclamation_marks(self) -> None:
        """验证supports question and exclamation marks场景下的预期结果。"""
        text = "为什么分散复习更稳？因为大脑需要间隔来重新提取信息！这个过程会加深记忆。"

        self.assertEqual(
            split_knowledge_bubble_text(text),
            [
                "为什么分散复习更稳？",
                "因为大脑需要间隔来重新提取信息！这个过程会加深记忆。",
            ],
        )

    # 验证normalizes whitespace场景下的预期结果。
    def test_normalizes_whitespace(self) -> None:
        """验证normalizes whitespace场景下的预期结果。"""
        text = "第一段内容足够长。\n\n第二句。"

        self.assertEqual(split_knowledge_bubble_text(text), ["第一段内容足够长。", "第二句。"])


    # 验证四十字阈值以内不触发分割。
    def test_informal_answer_below_threshold_is_unchanged(self) -> None:
        """验证四十字以内的非正式回答保持原文。"""
        text = "甲" * 39 + "。"
        self.assertEqual(split_informal_answer_text(text), [text])

    # 验证六十至八十字区间内的句号优先作为切点。
    def test_informal_answer_prefers_ideal_range(self) -> None:
        """验证六十至八十字区间内优先切分。"""
        first = "甲" * 64 + "。"
        second = "乙" * 20 + "。"
        self.assertEqual(split_informal_answer_text(first + second), [first, second])

    # 验证没有理想切点时使用一百二十字以内的最近句号。
    def test_informal_answer_uses_acceptable_range(self) -> None:
        """验证没有理想切点时仍在最大区间内切分。"""
        first = "甲" * 44 + "。"
        second = "乙" * 35 + "。"
        third = "丙" * 20
        self.assertEqual(split_informal_answer_text(first + second + third), [first, second + third])

    # 验证一百二十字内没有句号时继续等到下一个句号。
    def test_informal_answer_waits_for_next_period_after_maximum(self) -> None:
        """验证超过一百二十字仍只在句号处分割。"""
        first = "甲" * 129 + "。"
        second = "乙" * 20 + "。"
        self.assertEqual(split_informal_answer_text(first + second), [first, second])

    # 验证最多只生成三个气泡段落。
    def test_informal_answer_has_at_most_three_parts(self) -> None:
        """验证非正式回答最多分成三段。"""
        sentences = ["甲" * 64 + "。", "乙" * 64 + "。", "丙" * 64 + "。", "丁" * 20]
        parts = split_informal_answer_text("".join(sentences))
        self.assertEqual(len(parts), 3)
        self.assertEqual("".join(parts), "".join(sentences))


if __name__ == "__main__":
    unittest.main()
