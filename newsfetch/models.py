"""跨模块共享的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Candidate:
    """一张候选图片及其声明宽度（越大越可能是正文大图）。"""

    url: str
    declared_width: int = 0


@dataclass(frozen=True, slots=True)
class Article:
    """一篇抓取到的文章。"""

    content: str
    candidates: tuple[Candidate, ...]
    url: str

    def merged_candidates(self, extra: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
        """按“本文优先”的顺序合并其它来源的候选图片。"""
        return self.candidates + extra
