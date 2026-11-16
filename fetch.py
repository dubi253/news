# -*- coding: utf-8 -*-
"""Fetch categorized news with local article images."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
GOOGLE_NEWS_HOSTS = {"news.google.com", "www.news.google.com"}
AVATAR_MARKERS = {
    "avatar",
    "author",
    "headshot",
    "icon",
    "logo",
    "profile",
    "user",
}


def clean_text(value: str | None) -> str:
    """Decode HTML entities and normalize whitespace."""
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def iso_time(value: Any, default_timezone: str | None = None) -> str:
    """Convert an RSS date to UTC, requiring a timezone for naive values."""
    if not value:
        return ""
    try:
        if hasattr(value, "tm_year"):
            parsed = datetime(*value[:6])
        else:
            text = str(value).strip()
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            if not default_timezone:
                return ""
            parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        return ""


def published_time(
    entry: Mapping[str, Any],
    default_timezone: str | None = None,
) -> str:
    """Return the best available publication timestamp."""
    for key in ("published", "updated", "date", "created", "issued"):
        if entry.get(key):
            parsed = iso_time(entry[key], default_timezone)
            if parsed:
                return parsed
    for key in (
        "published_parsed",
        "updated_parsed",
        "date_parsed",
        "created_parsed",
        "issued_parsed",
    ):
        if entry.get(key):
            parsed = iso_time(entry[key], default_timezone)
            if parsed:
                return parsed
    return ""


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


def _image_candidate_score(source: str, descriptor: str = "") -> int:
    """Estimate an image candidate's resolution from srcset or URL metadata."""
    match = re.search(r"(\d{2,5})w\b", descriptor)
    if match:
        return int(match.group(1))
    for pattern in (r"(?:width|w|size)[=_-](\d{2,5})", r"[_-](\d{3,5})x\d{2,5}"):
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0


def _media_dimension(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_avatar(image: Tag) -> bool:
    """Reject common author/avatar/icon images."""
    text = " ".join(
        str(image.get(attribute, ""))
        for attribute in ("alt", "class", "id", "data-testid", "aria-label")
    ).lower()
    return any(re.search(rf"\b{re.escape(marker)}\b", text) for marker in AVATAR_MARKERS)


def html_images(value: str, base: str) -> list[str]:
    """Extract unique image URLs from HTML."""
    soup = BeautifulSoup(value or "", "lxml")
    result: list[str] = []
    for image in soup.find_all("img"):
        if _is_avatar(image):
            continue
        candidates: list[tuple[int, str]] = []
        for source in (
            image.get("src"),
            image.get("data-src"),
            image.get("data-original"),
            image.get("data-lazy-src"),
        ):
            resolved = absolute_url(source, base)
            if resolved and resolved not in result:
                candidates.append((_image_candidate_score(resolved), resolved))
        picture = image.find_parent("picture")
        if picture:
            source_tags = picture.find_all("source")
            for source_tag in source_tags:
                for candidate in str(source_tag.get("srcset", "")).split(","):
                    parts = candidate.strip().split()
                    if not parts:
                        continue
                    resolved = absolute_url(parts[0], base)
                    if resolved:
                        candidates.append(
                            (
                                _image_candidate_score(
                                    resolved, parts[1] if len(parts) > 1 else ""
                                ),
                                resolved,
                            )
                        )
        for candidate in str(image.get("srcset", "")).split(","):
            parts = candidate.strip().split()
            if not parts:
                continue
            resolved = absolute_url(parts[0], base)
            if resolved:
                candidates.append(
                    (_image_candidate_score(resolved, parts[1] if len(parts) > 1 else ""), resolved)
                )
        if candidates:
            result.append(max(candidates, key=lambda item: item[0])[1])
    for metadata in soup.find_all("meta", attrs={"property": "og:image"}):
        resolved = absolute_url(metadata.get("content"), base)
        if resolved and not is_non_article_image(resolved) and resolved not in result:
            result.append(resolved)
    return result


def rss_images(entry: Mapping[str, Any], base: str) -> list[str]:
    """Extract unique image URLs from common RSS media fields."""
    result: list[str] = []
    for key in ("media_content", "media_thumbnail"):
        candidates = []
        for item in entry.get(key, []) or []:
            source = absolute_url(item.get("url"), base)
            if source:
                width = _media_dimension(item.get("width"))
                height = _media_dimension(item.get("height"))
                candidates.append((width * height or width or height, source))
        if candidates:
            result.append(max(candidates, key=lambda item: item[0])[1])
    for enclosure in entry.get("enclosures", []) or []:
        if str(enclosure.get("type", "")).startswith("image"):
            source = absolute_url(enclosure.get("href") or enclosure.get("url"), base)
            if source and source not in result:
                result.append(source)
    return result


def fetch_article(link: str) -> tuple[str, list[str], str]:
    """Fetch a full article when the RSS entry is incomplete."""
    try:
        response = SESSION.get(link, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning("article fetch failed %s: %s", link, exc)
        return "", [], link

    resolved_link = response.url if response.url.startswith(("http://", "https://")) else link
    if is_google_news_url(resolved_link):
        LOGGER.warning("Google News URL did not resolve to a publisher: %s", link)
        return "", [], link
    soup = BeautifulSoup(response.text, "lxml")
    page_images = html_images(response.text, resolved_link)
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()
    article = soup.find("article") or soup.find("main") or soup
    article_html = str(article)
    return (
        html_to_markdown(article_html, resolved_link),
        page_images + html_images(article_html, resolved_link),
        resolved_link,
    )


def publisher_link(content_html: str, fallback: str) -> str:
    """Extract a publisher URL embedded in a Google News RSS description."""
    if (urlparse(fallback).hostname or "").lower() not in GOOGLE_NEWS_HOSTS:
        return fallback
    soup = BeautifulSoup(content_html or "", "lxml")
    for anchor in soup.find_all("a", href=True):
        candidate = absolute_url(anchor.get("href"), fallback)
        if candidate and (urlparse(candidate).hostname or "").lower() not in GOOGLE_NEWS_HOSTS:
            return candidate
    return fallback


def is_google_news_url(value: str) -> bool:
    """Return whether a URL belongs to Google News rather than a publisher."""
    return (urlparse(value).hostname or "").lower() in GOOGLE_NEWS_HOSTS


def has_read_more_marker(value: str) -> bool:
    """Return whether RSS content explicitly indicates that it is truncated."""
    if not value:
        return False
    soup = BeautifulSoup(html.unescape(value), "lxml")
    marker_text = " ".join(
        clean_text(node.get_text(" ", strip=True))
        for node in soup.find_all(["a", "button"])
    )
    marker_text = f"{marker_text} {clean_text(soup.get_text(' ', strip=True))}"
    return bool(
        re.search(
            r"\b(?:read\s+more|continue\s+reading|read\s+the\s+full)\b"
            r"|阅读全文|继续阅读|查看全文",
            marker_text,
            re.IGNORECASE,
        )
    )


def detect_language(entry: Mapping[str, Any], value: str) -> str:
    """Return a simple ISO 639-1 language code for a news item."""
    explicit = str(entry.get("language") or "").lower().split("-", 1)[0]
    if explicit in {"en", "zh"}:
        return explicit
    cjk = len(re.findall(r"[\u3400-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    if cjk:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def translate_to_chinese(values: list[str]) -> list[str]:
    """Translate text values with Google Cloud Translation when configured."""
    api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
    if not api_key or not values:
        return values
    translated_values: list[str] = []
    for value in values:
        translated_parts: list[str] = []
        parts = [value[index : index + 20_000] for index in range(0, len(value), 20_000)] or [""]
        for part in parts:
            try:
                response = SESSION.post(
                    "https://translation.googleapis.com/language/translate/v2",
                    params={"key": api_key},
                    json={"q": [part], "target": "zh-CN", "format": "text"},
                    timeout=TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                translated_parts.append(str(response.json()["data"]["translations"][0]["translatedText"]))
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                LOGGER.warning("translation failed: %s", exc)
                translated_parts = []
                break
        translated_values.append("".join(translated_parts) if translated_parts else value)
    return translated_values


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


def is_non_article_image(source: str) -> bool:
    """Reject common avatar, icon, logo, and tracking image URLs."""
    path = urlparse(source).path.lower()
    return any(
        re.search(rf"(^|[/_.-]){re.escape(marker)}([/_.-]|$)", path)
        for marker in AVATAR_MARKERS | {"favicon", "pixel", "tracking"}
    )


def download_image(source: str, index: int) -> str:
    """Download one image and return its repository-relative path."""
    if is_non_article_image(source):
        return ""
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
        destination = IMAGE_DIR / f"{digest}{image_extension(response, source)}"
        if not destination.exists():
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
        google_news_entry = is_google_news_url(link)
        link = publisher_link(content_html, link)
        content = html_to_markdown(content_html, link)
        image_sources = rss_images(entry, link) + html_images(content_html, link)
        truncated = has_read_more_marker(content_html)
        if google_news_entry or truncated or len(content) < 400 or not image_sources:
            fetched_content, fetched_images, resolved_link = fetch_article(link)
            if fetched_content and (google_news_entry or truncated or len(fetched_content) > len(content)):
                content = fetched_content
            if resolved_link != link and not is_google_news_url(resolved_link):
                link = resolved_link
            image_sources.extend(fetched_images)

        language = detect_language(entry, f"{title}\n{content}")
        if language == "en":
            translated = translate_to_chinese([title, content])
            title, content = translated

        local_images: list[str] = []
        for image_index, source in enumerate(dict.fromkeys(image_sources)):
            local_path = download_image(source, image_index)
            if local_path and local_path not in local_images:
                local_images.append(local_path)
            if len(local_images) >= MAX_IMAGES_PER_ITEM:
                break

        items.append(
            {
                "category": feed_config.category,
                "source": feed_config.source or parsed.feed.get("title", feed_config.url),
                "title": title,
                "language": language,
                "published": published_time(entry, feed_config.default_timezone),
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
