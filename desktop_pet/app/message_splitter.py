from __future__ import annotations

import re


SENTENCE_END_RE = re.compile(r"([。！？!?；;])")


# 根据 text、min_first_chars、max_parts 整理split 知识问候 气泡 文本，并把结果交给调用方或写回状态。
def split_knowledge_bubble_text(
    text: str,
    *,
    min_first_chars: int = 8,
    max_parts: int = 2,
) -> list[str]:
    """根据 text、min_first_chars、max_parts 整理split 知识问候 气泡 文本，并把结果交给调用方或写回状态。"""
    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    if max_parts <= 1:
        return [cleaned]

    sentences = _sentences(cleaned)
    if len(sentences) <= 1:
        return [cleaned]

    first_parts: list[str] = []
    first_len = 0
    split_index = 0
    for index, sentence in enumerate(sentences):
        first_parts.append(sentence)
        first_len += len(sentence)
        split_index = index + 1
        if first_len >= min_first_chars:
            break

    if split_index >= len(sentences):
        return [cleaned]

    first = "".join(first_parts).strip()
    second = "".join(sentences[split_index:]).strip()
    if not first or not second:
        return [cleaned]
    return [first, second]


# 合并文本空白字符，返回适合气泡分句的内容。
def _normalize_text(text: str) -> str:
    """合并文本空白字符，返回适合气泡分句的内容。"""
    return re.sub(r"\s+", " ", text.strip())


# 根据 text 按中英文标点拆分句子，过滤空白片段。
def _sentences(text: str) -> list[str]:
    """根据 text 按中英文标点拆分句子，过滤空白片段。"""
    parts = SENTENCE_END_RE.split(text)
    sentences: list[str] = []
    index = 0
    while index < len(parts):
        body = parts[index].strip()
        punctuation = parts[index + 1] if index + 1 < len(parts) else ""
        index += 2
        sentence = f"{body}{punctuation}".strip()
        if sentence:
            sentences.append(sentence)
    return sentences
