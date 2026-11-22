"""跨模块共享的数据结构。

``NewsItem`` 描述 ``data/news.json`` 中单条新闻的字段契约（字段只增不改），
``Candidate`` / ``Article`` 用于抓取过程中的图片候选与正文传递。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class NewsItem(TypedDict):
    """产物 ``data/news.json`` 中的一条新闻。

    Attributes:
        category: 分类，例如 ``semiconductor``。
        source: 来源名，与 ``FeedConfig.source`` 一致。
        title: 标题；英文条目在配置了翻译凭据时已是中文。
        language: 原始语种，``zh`` / ``en`` / ``unknown``。
        published: ISO 8601 带偏移的发布时间，无法判断时为空串。
        link: 原文地址。
        content: 纯文本 Markdown 正文，不含图片语法。
        images: 本地图片路径，形如 ``data/images/<hash>.<ext>``。
    """

    category: str
    source: str
    title: str
    language: str
    published: str
    link: str
    content: str
    images: list[str]


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
