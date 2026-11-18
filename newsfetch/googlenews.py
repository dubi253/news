"""Google News 搜索源。

Google News 的 RSS 只有标题和跳转链接，正文必须回到发布方页面取。
链接还原优先用 ``googlenewsdecoder``（纯 HTTP），失败的再用浏览器访问。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import feedparser

from config import FEED_HEADERS
from newsfetch import browser, http
from newsfetch.urls import host_of

LOGGER = logging.getLogger("newsfetch.googlenews")
GOOGLE_NEWS_HOSTS = frozenset({"news.google.com", "www.news.google.com"})
RESOLVE_TIMEOUT_MS = 20_000


def is_google_news_url(url: str) -> bool:
    """是否为 Google News 的跳转地址。"""
    return host_of(url) in GOOGLE_NEWS_HOSTS


def is_google_news_feed(url: str) -> bool:
    """是否为 Google News 的 RSS 搜索地址。"""
    parsed = urlparse(url)
    return host_of(url) in GOOGLE_NEWS_HOSTS and parsed.path.startswith("/rss")


def resolve_url(link: str) -> str:
    """把 Google News 跳转链接还原为发布方原始链接。"""
    if not is_google_news_url(link):
        return link
    decoded = _decode(link)
    if decoded:
        return decoded
    navigated = _navigate(link)
    if navigated:
        return navigated
    LOGGER.warning("无法还原 Google News 链接: %s", link)
    return link


def _decode(link: str) -> str:
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        LOGGER.warning("googlenewsdecoder 未安装，改用浏览器还原链接")
        return ""
    try:
        result = gnewsdecoder(link, interval=1)
    except Exception as exc:  # noqa: BLE001 - 该库对异常格式会抛各种错误
        LOGGER.info("Google News 解码失败 %s: %s", link, exc)
        return ""
    if not isinstance(result, Mapping) or not result.get("success"):
        return ""
    decoded = str(result.get("decoded_url") or "")
    return decoded if decoded.startswith(("http://", "https://")) else ""


def _navigate(link: str) -> str:
    """兜底：让浏览器跟着跳转，读出最终地址。"""
    navigate_url = link.replace("/rss/articles/", "/articles/").split("?", 1)[0]
    page = browser.render(
        navigate_url, wait_ms=1_000, timeout_ms=RESOLVE_TIMEOUT_MS, proxy=http.browser_proxy()
    )
    if page is None:
        return ""
    return "" if is_google_news_url(page.url) else page.url


def fetch_entries(feed_url: str, limit: int) -> list[dict[str, Any]]:
    """解析 Google News RSS，返回已还原链接的条目。

    Args:
        feed_url: RSS 搜索地址。
        limit: 最多返回的条目数。

    Returns:
        形如 ``{"title", "link", "published"}`` 的条目列表；链接还原失败的条目被丢弃。
    """
    response = http.get_bytes(feed_url, headers=FEED_HEADERS)
    if response is None:
        return []
    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        LOGGER.warning("Google News 无条目: %s", feed_url)
        return []

    entries: list[dict[str, Any]] = []
    for entry in parsed.entries[:limit]:
        link = resolve_url(str(entry.get("link") or ""))
        if not link or is_google_news_url(link):
            continue
        entries.append(
            {
                "title": entry.get("title", ""),
                "link": link,
                "published": entry.get("published", ""),
                "summary": "",
            }
        )
    return entries
