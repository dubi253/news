"""文本处理：HTML 实体、编码识别、乱码修复与语种判断。

部分站点没有在响应头里给出 charset，甚至故意用与声明不一致的编码输出
正文（表现为“乱码”）。这里统一按字节重新解码并挑选最可信的结果。
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any

from charset_normalizer import from_bytes

# 典型的编码错配产物：UTF-8 被当成 Latin-1 解读，或 GBK 被当成 UTF-8 解读。
MOJIBAKE_MARKERS = ("锟斤拷", "ï»¿", "â€™", "â€œ", "â€", "Ã¤", "Ã©", "Ã¼", "å¤", "æ–‡")
CHARSET_PATTERN = re.compile(rb"charset=[\"']?([\w.:-]+)", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")


def clean_text(value: str | None) -> str:
    """解码 HTML 实体并压缩空白。"""
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def mojibake_score(text: str) -> int:
    """估计乱码程度：替换字符与典型错配片段越多，分数越高。"""
    if not text:
        return 0
    score = text.count("\ufffd") * 10
    score += sum(text.count(marker) for marker in MOJIBAKE_MARKERS) * 8
    # Latin-1 补充区字符成片出现，通常意味着 UTF-8 被按单字节解码。
    latin_supplement = sum(1 for char in text if "\u0080" <= char <= "\u00ff")
    if latin_supplement > len(text) * 0.05:
        score += latin_supplement // 4
    return score


def _declared_charset(headers: Mapping[str, str], raw: bytes) -> str | None:
    """从响应头或 meta 标签里取声明编码。"""
    content_type = headers.get("Content-Type", "") if headers else ""
    match = re.search(r"charset=([\w.:-]+)", content_type, re.IGNORECASE)
    if match:
        return match.group(1)
    match = CHARSET_PATTERN.search(raw[:4096])
    return match.group(1).decode("ascii", "ignore") if match else None


def _candidate_encodings(declared: str | None) -> list[str]:
    encodings = [declared, "utf-8", "gb18030", "big5", "latin-1"]
    return [encoding for encoding in encodings if encoding]


def _decode_best(raw: bytes, encodings: list[str]) -> str:
    best_text, best_score = "", -1
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError, LookupError:
            continue
        score = 1 - mojibake_score(text) / max(len(text), 1)
        if score > best_score:
            best_text, best_score = text, score
    return best_text


def repair_mojibake(text: str) -> str:
    """把“UTF-8 被当成单字节编码”的文本还原，失败时原样返回。"""
    if not text or mojibake_score(text) == 0:
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except UnicodeEncodeError, UnicodeDecodeError:
        return text
    return repaired if mojibake_score(repaired) < mojibake_score(text) else text


def decode_body(raw: bytes, headers: Mapping[str, str] | None = None) -> str:
    """按声明编码、常见编码与 charset-normalizer 的推断依次尝试解码。"""
    if not raw:
        return ""
    encodings = _candidate_encodings(_declared_charset(headers or {}, raw))
    best = from_bytes(raw).best()
    if best and best.encoding:
        encodings.append(best.encoding)
    text = _decode_best(raw, encodings)
    if not text:
        text = raw.decode("utf-8", "replace")
    return repair_mojibake(text)


def detect_language(entry: Mapping[str, Any], value: str) -> str:
    """返回简单的语种代码：zh / en / unknown。"""
    explicit = str(entry.get("language") or "").lower().split("-", 1)[0]
    if explicit in {"en", "zh"}:
        return explicit
    if CJK_PATTERN.search(value):
        return "zh"
    if LATIN_PATTERN.search(value):
        return "en"
    return "unknown"


def normalize_markdown(value: str, max_length: int) -> str:
    """收敛多余空行并截断到约定长度。"""
    text = re.sub(r"[ \t]+\n", "\n", value or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_length].strip()
