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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
OUTPUT_PATH = DATA_DIR / "news.json"
TIMEOUT = 20
MAX_PER_FEED = 8
MAX_ITEMS = 120
MAX_CONTENT_LENGTH = 50000
USER_AGENT = "Mozilla/5.0 (compatible; dubi253-news/2.0; +https://github.com/dubi253/news)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en,zh-CN;q=0.8"}

FEEDS = [
    {"category": "international", "source": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "limit": 6},
    {"category": "international", "source": "The Guardian World", "url": "https://www.theguardian.com/world/rss", "limit": 6},
    {"category": "international", "source": "德国之声中文", "url": "https://rss.dw.com/rdf/rss-chi-all", "limit": 6},
    {"category": "international", "source": "联合早报国际", "url": "https://www.zaobao.com.sg/rss/realtime/world", "limit": 6},
    {"category": "technology", "source": "TechCrunch", "url": "https://techcrunch.com/feed/", "limit": 6},
    {"category": "technology", "source": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "limit": 6},
    {"category": "technology", "source": "36氪", "url": "https://36kr.com/feed", "limit": 6},
    {"category": "technology", "source": "爱范儿", "url": "https://www.ifanr.com/feed", "limit": 6},
    {"category": "ai", "source": "MIT AI", "url": "https://news.mit.edu/rss/topic/artificial-intelligence2", "limit": 18},
    {"category": "ai", "source": "QbitAI量子位", "url": "https://www.qbitai.com/feed", "limit": 18},
    {"category": "ai", "source": "机器之心", "url": "https://www.jiqizhixin.com/rss", "limit": 18},
    {"category": "semiconductor", "source": "Semiconductor Engineering", "url": "https://semiengineering.com/feed/", "limit": 18},
    {"category": "semiconductor", "source": "Tom's Hardware", "url": "https://www.tomshardware.com/feeds/all", "limit": 18},
    {"category": "semiconductor", "source": "电子工程专辑", "url": "https://www.eet-china.com/rss.xml", "limit": 18},
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news")
session = requests.Session()
session.headers.update(HEADERS)


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def iso_time(value) -> str:
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


def published_time(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return iso_time(entry[key])
    return iso_time(entry.get("published") or entry.get("updated"))


def absolute_url(value: str, base: str) -> str:
    if not value:
        return ""
    value = html.unescape(value.strip())
    if value.startswith("//"):
        value = "https:" + value
    value = urljoin(base, value)
    return value if value.startswith(("http://", "https://")) else ""


def entry_html(entry) -> str:
    content = entry.get("content") or []
    if content and isinstance(content[0], dict):
        return content[0].get("value", "")
    return entry.get("summary", "") or entry.get("description", "")


def html_to_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<\s*img\b[^>]*>", " ", value, flags=re.IGNORECASE)
    soup = BeautifulSoup(value, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "form", "img"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"<\s*img\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CONTENT_LENGTH].strip()


def html_images(value: str, base: str) -> list[str]:
    soup = BeautifulSoup(value or "", "lxml")
    result = []
    for image in soup.find_all("img"):
        source = image.get("src") or image.get("data-src") or image.get("data-original")
        source = absolute_url(source, base)
        if source and source not in result:
            result.append(source)
    return result


def rss_images(entry, base: str) -> list[str]:
    result = []
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
    try:
        response = session.get(link, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup
        text = html_to_text(str(article))
        images = html_images(str(article), link)
        return text, images
    except requests.RequestException as exc:
        log.warning("article fetch failed %s: %s", link, exc)
        return "", []


def image_extension(response: requests.Response, source: str) -> str:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    extension = mimetypes.guess_extension(content_type) if content_type.startswith("image/") else None
    if extension in {".jpe", ".jpeg", ".jpg", ".png", ".gif", ".webp", ".avif"}:
        return ".jpg" if extension == ".jpe" else extension
    suffix = Path(urlparse(source).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"} else ".jpg"


def image_headers(source: str) -> dict[str, str]:
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
    try:
        response = session.get(source, headers=image_headers(source), timeout=TIMEOUT, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not content_type.startswith("image/"):
            return ""
        data = response.content
        if not data or len(data) > 15 * 1024 * 1024:
            return ""
        digest = hashlib.sha256(data).hexdigest()[:16]
        filename = f"{digest}-{index}{image_extension(response, source)}"
        destination = IMAGE_DIR / filename
        destination.write_bytes(data)
        return str(destination.relative_to(BASE_DIR)).replace(os.sep, "/")
    except (requests.RequestException, OSError) as exc:
        log.warning("image download failed %s: %s", source, exc)
        return ""


def fetch_feed(feed_config: dict) -> list[dict]:
    url = feed_config["url"]
    log.info("fetching %s", url)
    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except (requests.RequestException, ValueError) as exc:
        log.warning("feed failed %s: %s", url, exc)
        return []

    if not parsed.entries:
        log.warning("feed has no entries: %s", url)
        return []

    items = []
    limit = feed_config.get("limit", MAX_PER_FEED)
    for entry in parsed.entries[:limit]:
        title = clean_text(entry.get("title", ""))
        link = absolute_url(entry.get("link", ""), url)
        if not title or not link:
            continue
        content_html = entry_html(entry)
        text = html_to_text(content_html)
        image_sources = rss_images(entry, link) + html_images(content_html, link)
        if len(text) < 400 or not image_sources:
            fetched_text, fetched_images = fetch_article(link)
            if len(fetched_text) > len(text):
                text = fetched_text
            image_sources.extend(fetched_images)

        local_images = []
        for image_index, source in enumerate(dict.fromkeys(image_sources)):
            local_path = download_image(source, image_index)
            if local_path:
                local_images.append(local_path)
            if len(local_images) >= 3:
                break

        items.append({
            "category": feed_config["category"],
            "source": feed_config["source"] or parsed.feed.get("title", url),
            "title": title,
            "published": published_time(entry),
            "link": link,
            "content": text,
            "images": local_images,
        })
    return items


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if IMAGE_DIR.exists():
        shutil.rmtree(IMAGE_DIR)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    items = []
    seen = set()
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
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("wrote %d items to %s", len(items), OUTPUT_PATH)


if __name__ == "__main__":
    main()
