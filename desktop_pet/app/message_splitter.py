from __future__ import annotations

import re


SENTENCE_END_RE = re.compile(r"([。！？!?；;])")


def split_knowledge_bubble_text(
    text: str,
    *,
    min_first_chars: int = 8,
    max_parts: int = 2,
) -> list[str]:
    """Split a knowledge greeting into display-friendly bubble chunks."""
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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _sentences(text: str) -> list[str]:
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
