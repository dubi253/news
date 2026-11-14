# -*- coding: utf-8 -*-
"""Fetch categorized news with local article images."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import mimetypes
import re
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from config import (
    BASE_DIR,
    DATA_DIR,
    FEEDS,
    HEADERS,
    IMAGE_DIR,
    MAX_CONTENT_LENGTH,
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_ITEM,
    MAX_ITEMS,
    MAX_PER_FEED,
    OUTPUT_PATH,
    TIMEOUT_SECONDS,
    FeedConfig,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("news")
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}
BLOCK_TAGS = {"blockquote", "li", "p"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def clean_text(value: str | None) -> str:
    """Decode HTML entities and normalize whitespace."""
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def iso_time(value: Any) -> str:
    """Convert RSS date values to a UTC ISO-8601 string."""
    if not value:
        return ""
    try:
        if hasattr(value, "tm_year"):
            return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
        parsed = parsedate_to_datetime(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def published_time(entry: Mapping[str, Any]) -> str:
    """Return the best available publication timestamp."""
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return iso_time(entry[key])
    return iso_time(entry.get("published") or entry.get("updated"))


def absolute_url(value: str | None, base: str) -> str:
    """Resolve a URL and reject unsupported schemes."""
    if not value:
        return ""
    resolved = html.unescape(value.strip())
    if resolved.startswith("//"):
        resolved = f"https:{resolved}"
    resolved = urljoin(base, resolved)
    return resolved if resolved.startswith(("http://", "https://")) else ""


def entry_html(entry: Mapping[str, Any]) -> str:
    """Extract HTML content from an RSS entry."""
    content = entry.get("content") or []
    if content and isinstance(content[0], Mapping):
        return str(content[0].get("value", ""))
    return str(entry.get("summary") or entry.get("description") or "")


def _inline_markdown(node: Tag | NavigableString, base_url: str) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))

    content = "".join(_inline_markdown(child, base_url) for child in node.children)
    tag_name = node.name.lower()
    if tag_name in {"strong", "b"}:
        return f"**{content.strip()}**"
    if tag_name in {"em", "i"}:
        return f"*{content.strip()}*"
    if tag_name == "code":
        return f"`{content.strip()}`"
    if tag_name == "a":
        link = absolute_url(node.get("href"), base_url)
        return f"[{content.strip()}]({link})" if link else content
    if tag_name == "br":
        return "\n"
    return content


def html_to_markdown(value: str, base_url: str = "") -> str:
    """Convert article HTML into readable Markdown paragraphs."""
    if not value:
        return ""
    soup = BeautifulSoup(html.unescape(value), "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "form", "img"]):
        tag.decompose()

    blocks: list[str] = []
    for node in soup.find_all(list(BLOCK_TAGS | HEADING_TAGS)):
        if node.name == "li" and node.find_parent("li"):
            continue
        text = _inline_markdown(node, base_url).strip()
        if not text:
            continue
        if node.name in HEADING_TAGS:
            level = int(node.name[1])
            blocks.append(f'{"#" * level} {text}')
        elif node.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)

    if not blocks:
        blocks.append(_inline_markdown(soup, base_url).strip())
    markdown = "\n\n".join(blocks)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown[:MAX_CONTENT_LENGTH].strip()


def html_images(value: str, base: str) -> list[str]:
    """Extract unique image URLs from HTML."""
    soup = BeautifulSoup(value or "", "lxml")
    result: list[str] = []
    for image in soup.find_all("img"):
        source = image.get("src") or image.get("data-src") or image.get("data-original")
        resolved = absolute_url(source, base)
        if resolved and resolved not in result:
            result.append(resolved)
    return result


def rss_images(entry: Mapping[str, Any], base: str) -> list[str]:
    """Extract unique image URLs from common RSS media fields."""
    result: list[str] = []
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key, []) or []:
            source = absolute_url(item.get("url"), base)
            if source and source not in result:
                result.append(source)
    for enclosure in entry.get("enclosures", []) or []:
        if str(enclosure.get("type", "")).startswith("image"):
            source = absolute_url(enclosure.get("href") or enclosure.get("url"), base)
            if source and source not in result:
                result.append(source)
    return result


def fetch_article(link: str) -> tuple[str, list[str]]:
    """Fetch a full article when the RSS entry is incomplete."""
    try:
        response = SESSION.get(link, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning("article fetch failed %s: %s", link, exc)
        return "", []

    soup = BeautifulSoup(response.text, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()
    article = soup.find("article") or soup.find("main") or soup
    article_html = str(article)
    return html_to_markdown(article_html, link), html_images(article_html, link)


def image_extension(response: requests.Response, source: str) -> str:
    """Determine a safe local image extension."""
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    extension = mimetypes.guess_extension(content_type) if content_type.startswith("image/") else None
    if extension in IMAGE_EXTENSIONS:
        return ".jpg" if extension == ".jpe" else extension
    suffix = Path(urlparse(source).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


def image_headers(source: str) -> dict[str, str]:
    """Build headers used by image hosts that validate the referrer."""
    parsed = urlparse(source)
    host = parsed.hostname or ""
    referer_host = host[2:] if host.startswith("i.") else host
    if referer_host == "qbitai.com":
        referer_host = "www.qbitai.com"
    return {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": f"{parsed.scheme or 'https'}://{referer_host}/",
    }


def download_image(source: str, index: int) -> str:
    """Download one image and return its repository-relative path."""
    try:
        response = SESSION.get(
            source,
            headers=image_headers(source),
            timeout=TIMEOUT_SECONDS,
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not content_type.startswith("image/"):
            return ""
        data = response.content
        if not data or len(data) > MAX_IMAGE_BYTES:
            return ""
        digest = hashlib.sha256(data).hexdigest()[:16]
        destination = IMAGE_DIR / f"{digest}-{index}{image_extension(response, source)}"
        destination.write_bytes(data)
        return str(destination.relative_to(BASE_DIR)).replace("\\", "/")
    except (requests.RequestException, OSError) as exc:
        LOGGER.warning("image download failed %s: %s", source, exc)
        return ""


def fetch_feed(feed_config: FeedConfig) -> list[dict[str, Any]]:
    """Fetch and normalize entries from one configured RSS feed."""
    LOGGER.info("fetching %s", feed_config.url)
    try:
        response = SESSION.get(feed_config.url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        LOGGER.warning("feed failed %s: %s", feed_config.url, exc)
        return []

    if not parsed.entries:
        LOGGER.warning("feed has no entries: %s", feed_config.url)
        return []

    items: list[dict[str, Any]] = []
    for entry in parsed.entries[: feed_config.limit or MAX_PER_FEED]:
        title = clean_text(entry.get("title"))
        link = absolute_url(entry.get("link"), feed_config.url)
        if not title or not link:
            continue

        content_html = entry_html(entry)
        content = html_to_markdown(content_html, link)
        image_sources = rss_images(entry, link) + html_images(content_html, link)
        if len(content) < 400 or not image_sources:
            fetched_content, fetched_images = fetch_article(link)
            if len(fetched_content) > len(content):
                content = fetched_content
            image_sources.extend(fetched_images)

        local_images: list[str] = []
        for image_index, source in enumerate(dict.fromkeys(image_sources)):
            local_path = download_image(source, image_index)
            if local_path:
                local_images.append(local_path)
            if len(local_images) >= MAX_IMAGES_PER_ITEM:
                break

        items.append(
            {
                "category": feed_config.category,
                "source": feed_config.source or parsed.feed.get("title", feed_config.url),
                "title": title,
                "published": published_time(entry),
                "link": link,
                "content": content,
                "images": local_images,
            }
        )
    return items


def main() -> None:
    """Fetch all configured feeds and write the latest news snapshot."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if IMAGE_DIR.exists():
        shutil.rmtree(IMAGE_DIR)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feed in FEEDS:
        for item in fetch_feed(feed):
            if item["link"] not in seen:
                seen.add(item["link"])
                items.append(item)

    items.sort(key=lambda item: item["published"] or "", reverse=True)
    items = items[:MAX_ITEMS]
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "categories": sorted({item["category"] for item in items}),
        "items": items,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("wrote %d items to %s", len(items), OUTPUT_PATH)


if __name__ == "__main__":
    main()
