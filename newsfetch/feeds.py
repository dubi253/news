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


def build_item(entry: Mapping[str, Any], feed_config: FeedConfig) -> NewsItem | None:
    """把一个条目转换成产物条目；缺少标题或链接时返回 None。"""
    title = clean_text(entry.get("title"))
    link = absolute_url(entry.get("link") or entry.get("id"), feed_config.url)
    if not title or not link:
        return None
    link = wechat.unwrap_captcha_url(googlenews.resolve_url(link))

    content_html = entry_html(entry)
    content = extract.fragment_to_markdown(content_html)
    candidates = _collect_candidates(entry, content_html, link)
    published = dates.published_time(entry, feed_config.timezone)
    truncated = extract.has_read_more_marker(content_html)
    # 公众号镜像 RSS 不带 pubDate，必须回原文才能拿到发布时间。
    needs_publish_time = not published and wechat.is_wechat_url(link)
    if truncated or len(content) < MIN_ARTICLE_CHARS or not candidates or needs_publish_time:
        fetched = article_fetcher.fetch(link)
        if fetched.content and (truncated or len(fetched.content) > len(content)):
            content = fetched.content
        candidates.extend(fetched.candidates)
        published = published or fetched.published

    language = detect_language(entry, f"{title}\n{content}")
    if language == "en":
        title, content = to_chinese([title, content])

    selected = images.rank(candidates)
    local_images = images.download(selected, IMAGE_DIR, MAX_IMAGES_PER_ITEM)
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


def fetch_feed(feed_config: FeedConfig) -> list[NewsItem]:
    """抓取单个订阅源，返回规范化后的条目列表。"""
    LOGGER.info("抓取订阅源 %s", feed_config.source)
    items: list[NewsItem] = []
    for entry in _load_entries(feed_config)[: _limit(feed_config)]:
        item = build_item(entry, feed_config)
        if item is not None:
            items.append(item)
    LOGGER.info("%s 得到 %d 条", feed_config.source, len(items))
    return items
