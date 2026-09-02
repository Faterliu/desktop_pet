from __future__ import annotations

import re


SENTENCE_END_RE = re.compile(r"([。！？!?；;])")
INFORMAL_ANSWER_MIN_CHARS = 40
INFORMAL_ANSWER_IDEAL_MIN_CHARS = 60
INFORMAL_ANSWER_IDEAL_MAX_CHARS = 80
INFORMAL_ANSWER_MAX_CHARS = 120


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


# 按中文句号把非正式回答拆成适合气泡展示的最多三段。
def split_informal_answer_text(
    text: str,
    *,
    min_chars: int = INFORMAL_ANSWER_MIN_CHARS,
    ideal_min_chars: int = INFORMAL_ANSWER_IDEAL_MIN_CHARS,
    ideal_max_chars: int = INFORMAL_ANSWER_IDEAL_MAX_CHARS,
    max_chars: int = INFORMAL_ANSWER_MAX_CHARS,
    max_parts: int = 3,
) -> list[str]:
    """按长度区间寻找句号切分非正式回答，不在句子中间强行截断。"""
    cleaned = _normalize_text(text)
    if not cleaned or len(cleaned) <= min_chars or max_parts <= 1:
        return [cleaned] if cleaned else []

    parts: list[str] = []
    remaining = cleaned
    while len(parts) < max_parts - 1 and len(remaining) > min_chars:
        boundaries = [
            match.end()
            for match in re.finditer("。", remaining)
            if match.end() >= min_chars
        ]
        if not boundaries:
            break

        ideal_boundaries = [
            boundary for boundary in boundaries if ideal_min_chars <= boundary <= ideal_max_chars
        ]
        if ideal_boundaries:
            split_at = ideal_boundaries[0]
        else:
            acceptable_boundaries = [boundary for boundary in boundaries if boundary <= max_chars]
            split_at = acceptable_boundaries[0] if acceptable_boundaries else boundaries[0]

        part = remaining[:split_at].strip()
        if not part:
            break
        parts.append(part)
        remaining = remaining[split_at:].strip()

    if remaining:
        parts.append(remaining)
    return parts


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
