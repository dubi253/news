"""跨源同一稿件的去重。

同一个事件常被多个源收录：澎湃与新华社通稿、Google News 的中英文搜索源、
公众号与门户转载。它们的链接不同，链接去重管不到，产物里就会出现两条内容
几乎一样的新闻。这里按归一化标题合并，保留信息更全的一条。

只做保守合并：标题高度相似且发布时间接近才认为是同一稿件，避免把同一来源
的系列报道（“财报解读（一）/（二）”）误合成一条。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from difflib import SequenceMatcher

from newsfetch.models import NewsItem

# Google News 等聚合源会在标题尾部拼上发布方名称。只当尾部明显比标题短时才当成
# 发布方——人民日报的“01版 - 李强同新加坡总理黄循财会谈”是版次+标题，
# 整段剥掉会退化成“01版”，让同版不同稿互相合并。
TITLE_SUFFIX = re.compile(r"^(?P<title>.+?)\s+[-–—|_]\s+(?P<suffix>[^-–—_|]{1,20})$")
NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
# 标题相似度阈值：0.9 能合并同稿的通稿改写，又不会把“（上）/（下）”算成一篇。
SIMILARITY_THRESHOLD = 0.9
# 归一化后短于该长度的标题太泛（“国内要闻”“早报”），只按完全相等合并。
MIN_FUZZY_TITLE = 8
# 同一稿件在不同源的发布时间可能相差几小时，但不会相差几天。
MAX_HOURS_APART = 48


def normalize_title(title: str) -> str:
    """去掉来源后缀、标点与空白，用于标题比较。"""
    text = (title or "").strip()
    match = TITLE_SUFFIX.match(text)
    if match and len(match.group("suffix")) < len(match.group("title")):
        text = match.group("title")
    return NON_WORD.sub("", text.lower())


def _published_at(item: NewsItem) -> datetime | None:
    try:
        return datetime.fromisoformat(item["published"])
    except TypeError, ValueError:
        return None


def _close_in_time(left: NewsItem, right: NewsItem) -> bool:
    """发布时间相差在阈值内；任一侧没有时间时不做时间判断。"""
    left_at, right_at = _published_at(left), _published_at(right)
    if left_at is None or right_at is None:
        return True
    return abs((left_at - right_at).total_seconds()) <= MAX_HOURS_APART * 3600


def _is_same_story(left: NewsItem, right: NewsItem) -> bool:
    left_title, right_title = normalize_title(left["title"]), normalize_title(right["title"])
    if not left_title or not right_title:
        return False
    if left_title == right_title:
        return _close_in_time(left, right)
    if not _close_in_time(left, right):
        return False
    if min(len(left_title), len(right_title)) < MIN_FUZZY_TITLE:
        return False
    return SequenceMatcher(None, left_title, right_title).ratio() >= SIMILARITY_THRESHOLD


def _score(item: NewsItem) -> tuple[int, int, str]:
    """同一稿件的取舍顺序：有配图 > 正文更长 > 发布更早。"""
    return (1 if item["images"] else 0, len(item["content"]), item["published"] or "")


def dedupe(items: Sequence[NewsItem]) -> tuple[list[NewsItem], int]:
    """合并同一稿件，保留信息更全的一条并保持首次出现的位置。

    Args:
        items: 已按链接去重的条目。

    Returns:
        (去重后的条目, 被合并掉的条数)。
    """
    kept: list[NewsItem] = []
    dropped = 0
    for item in items:
        for index, existing in enumerate(kept):
            if not _is_same_story(existing, item):
                continue
            dropped += 1
            if _score(item) > _score(existing):
                kept[index] = item
            break
        else:
            kept.append(item)
    return kept, dropped
