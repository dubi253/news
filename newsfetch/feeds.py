"""订阅源抓取：把 RSS / Google News 条目转换成产物条目。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import feedparser

from config import (
    BASE_DIR,
    FEED_HEADERS,
    IMAGE_DIR,
    MAX_IMAGES_PER_ITEM,
    MAX_IMAGES_PER_WECHAT_ITEM,
    MAX_PER_FEED,
    MIN_ARTICLE_CHARS,
    FeedConfig,
)
from newsfetch import article as article_fetcher
from newsfetch import dates, extract, googlenews, http, images, wechat
from newsfetch.models import Candidate, NewsItem
from newsfetch.text import clean_text, detect_language
from newsfetch.translate import to_chinese
from newsfetch.urls import absolute_url

LOGGER = logging.getLogger("newsfetch.feeds")
# 产物里的图片路径以仓库根为基准，例如 data/images/<hash>.jpg。
IMAGE_PREFIX = IMAGE_DIR.relative_to(BASE_DIR).as_posix()


def entry_html(entry: Mapping[str, Any]) -> str:
    """取出条目自带的 HTML 正文/摘要。"""
    content = entry.get("content") or []
    if content and isinstance(content[0], Mapping):
        return str(content[0].get("value", ""))
    return str(entry.get("summary") or entry.get("description") or "")


def _limit(feed_config: FeedConfig) -> int:
    return feed_config.limit or MAX_PER_FEED


def _load_entries(feed_config: FeedConfig) -> list[Mapping[str, Any]]:
    """读取订阅源条目；Google News 走单独的解析路径。"""
    if googlenews.is_google_news_feed(feed_config.url):
        return list(googlenews.fetch_entries(feed_config.url, _limit(feed_config)))

    response = http.get_bytes(feed_config.url, headers=FEED_HEADERS)
    if response is None:
        return []
    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        LOGGER.warning("订阅源没有条目: %s", feed_config.url)
        return []
    return list(parsed.entries)


def _collect_candidates(
    entry: Mapping[str, Any],
    entry_content_html: str,
    link: str,
) -> list[Candidate]:
    return images.collect_from_html(entry_content_html, link) + images.collect_from_rss(entry, link)


def _reusable(previous: Mapping[str, NewsItem] | None, link: str, title: str) -> NewsItem | None:
    """上一轮抓到的同一篇稿件，可以直接复用它的正文与图片。

    新闻稿一旦发布极少改动，链接和标题都没变就认为内容没变；标题变了说明
    站点改稿，重新抓一遍更稳妥。复用的图片必须仍在本地，否则产物会引用
    不存在的文件。
    """
    if not previous:
        return None
    cached = previous.get(link)
    if cached is None or cached.get("title") != title:
        return None
    if len(cached.get("content") or "") < MIN_ARTICLE_CHARS:
        return None
    # 上一轮没抓到配图的条目不复用：它正是需要重试修好的那批，复用会把缺陷固化。
    if not cached.get("images"):
        return None
    if not all((BASE_DIR / path).is_file() for path in cached.get("images") or []):
        return None
    return cached


def build_item(
    entry: Mapping[str, Any],
    feed_config: FeedConfig,
    previous: Mapping[str, NewsItem] | None = None,
) -> NewsItem | None:
    """把一个条目转换成产物条目；缺少标题或链接时返回 None。

    Args:
        entry: RSS 条目。
        feed_config: 该条目所属的订阅源配置。
        previous: 上一轮快照的 link → 条目索引，命中时直接复用，省掉回访原文。

    Returns:
        产物条目；标题或链接缺失时返回 None。
    """
    title = clean_text(entry.get("title"))
    link = absolute_url(entry.get("link") or entry.get("id"), feed_config.url)
    if not title or not link:
        return None
    link = wechat.unwrap_captcha_url(googlenews.resolve_url(link))
    cached = _reusable(previous, link, title)
    if cached is not None:
        return {
            "category": feed_config.category,
            "source": feed_config.source,
            "title": cached["title"],
            "language": cached["language"],
            "published": cached["published"],
            "link": cached["link"],
            "content": cached["content"],
            "images": list(cached["images"]),
        }

    content_html = entry_html(entry)
    content = extract.fragment_to_markdown(content_html)
    candidates = _collect_candidates(entry, content_html, link)
    published = dates.published_time(entry, feed_config.timezone)
    truncated = extract.has_read_more_marker(content_html)
    image_limit = MAX_IMAGES_PER_WECHAT_ITEM if wechat.is_wechat_url(link) else MAX_IMAGES_PER_ITEM

    def refresh_from_article() -> None:
        """回访原文，把正文更长的一份与图片候选并入当前条目。"""
        fetched = article_fetcher.fetch(link)
        nonlocal content, published
        if fetched.content and (truncated or len(fetched.content) > len(content)):
            content = fetched.content
        candidates.extend(fetched.candidates)
        published = published or fetched.published

    # 回访原文的四种理由：摘要被截断、正文过短、没有可用大图、没有发布时间。
    # 注意用 rank() 之后的结果判断“有没有图”——RSS 摘要里常带图标级 <img>，
    # 候选非空并不代表有正文配图；公众号镜像不带 pubDate，也只有回原文才有时间。
    visited = False
    if (
        truncated
        or len(content) < MIN_ARTICLE_CHARS
        or not images.rank(candidates)
        or not published
    ):
        refresh_from_article()
        visited = True

    local_images = images.download(images.rank(candidates), IMAGE_DIR, image_limit)
    if not local_images and not visited:
        # 候选都是“下载后不达标”的站点素材（人民日报的 go_top.png 这类），
        # rank() 拦不住，只有真的下一遍才知道没有大图；此时再回访原文补图。
        refresh_from_article()
        local_images = images.download(images.rank(candidates), IMAGE_DIR, image_limit)

    language = detect_language(entry, f"{title}\n{content}")
    if language == "en":
        title, content = to_chinese([title, content])

    return {
        "category": feed_config.category,
        "source": feed_config.source,
        "title": title,
        "language": language,
        "published": published,
        "link": link,
        "content": content,
        "images": [f"{IMAGE_PREFIX}/{path.name}" for path in local_images],
    }


def fetch_feed(
    feed_config: FeedConfig, previous: Mapping[str, NewsItem] | None = None
) -> list[NewsItem]:
    """抓取单个订阅源，返回规范化后的条目列表。

    Args:
        feed_config: 订阅源配置。
        previous: 上一轮快照索引，命中时该条目直接复用，不再回访原文。
    """
    LOGGER.info("抓取订阅源 %s", feed_config.source)
    items: list[NewsItem] = []
    for entry in _load_entries(feed_config)[: _limit(feed_config)]:
        item = build_item(entry, feed_config, previous)
        if item is not None:
            items.append(item)
    LOGGER.info("%s 得到 %d 条", feed_config.source, len(items))
    return items
