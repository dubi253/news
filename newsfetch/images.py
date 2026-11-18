"""图片候选收集、高清筛选与本地化。

只保留新闻正文里应有的大图：

* 按 URL 归一化去重，同一张图的不同分辨率只留最高清的那份；
* 下载后按真实像素尺寸、宽高比和字节数复核，滤掉图标、头像、站点素材；
* 用内容哈希命名落盘，避免重复下载。
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Mapping
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from config import (
    MAX_IMAGE_ASPECT,
    MAX_IMAGE_BYTES,
    MIN_IMAGE_ASPECT,
    MIN_IMAGE_BYTES,
    MIN_IMAGE_HEIGHT,
    MIN_IMAGE_WIDTH,
)
from newsfetch import http
from newsfetch.models import Candidate
from newsfetch.urls import absolute_url

LOGGER = logging.getLogger("newsfetch.images")
SUPPORTED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "AVIF": ".avif"}
NON_ARTICLE_MARKERS = (
    "avatar",
    "author",
    "headshot",
    "icon",
    "logo",
    "profile",
    "user",
    "favicon",
    "pixel",
    "tracking",
    "sprite",
    "badge",
    "qrcode",
    "erweima",
    "placeholder",
    "spacer",
    "blank",
    "default",
    "share",
    "emoji",
    "arrow",
    "loading",
    "watermark",
)
# 只影响尺寸/格式的查询参数，去掉后仍指向同一张图。
RENDITION_QUERY_KEYS = {
    "w",
    "width",
    "h",
    "height",
    "q",
    "quality",
    "resize",
    "fit",
    "crop",
    "x-oss-process",
    "imageview2",
    "imageslim",
    "thumbnail",
    "size",
    "scale",
    "compress",
}
# 七牛这类把处理参数写成 `imageMogr2/quality/90` 的语法，整段都是渲染参数。
RENDITION_QUERY_PREFIXES = ("imagemogr2",)
# 带签名的地址不能改查询串：Guardian 的 `s=`、S3 的 `X-Amz-*` 都是对参数签名，
# 少一个参数就是 401，宁可原样下载。
SIGNATURE_QUERY_KEYS = {
    "s",
    "sig",
    "sign",
    "signature",
    "token",
    "auth",
    "expires",
    "hmac",
    "hash",
    "key",
}
SRCSET_SPLIT = re.compile(r",\s*")
WIDTH_DESCRIPTOR = re.compile(r"(\d{2,5})w$")
SCALE_DESCRIPTOR = re.compile(r"(\d(?:\.\d)?)x$")
SIZE_TOKEN = re.compile(r"(?:[-_/])(\d{2,4})x(\d{2,4})(?=[._/-]|$)")
RESIZED_FILENAME = re.compile(r"-\d{2,4}x\d{2,4}(?=\.\w+$)")
# 从 URL 里猜出渲染宽度：WordPress 的 -1024x768 后缀、?w=640、以及 /640/ 这类尺寸目录。
URL_SIZE_SUFFIX = re.compile(r"(?:[-_])(\d{2,4})x\d{2,4}(?=[._?/-]|$)")
URL_WIDTH_PARAM = re.compile(r"[?&](?:w|width)=(\d{2,4})")
URL_WIDTH_DIRECTORY = re.compile(r"/(\d{2,4})(?=[/.?]|$)")


def is_non_article(url: str) -> bool:
    """按 URL 特征排除头像、图标、二维码等站点素材。"""
    path = urlparse(url).path.lower()
    return any(re.search(rf"(^|[/_.-]){marker}([/_.-]|$)", path) for marker in NON_ARTICLE_MARKERS)


def _strip_rendition_query(query: str) -> str:
    """删掉只影响渲染的查询参数，其余部分按原样保留。

    不能用 ``parse_qsl`` + ``urlencode`` 重编码：七牛的处理参数是
    ``imageMogr2/quality/90`` 这种没有键值的写法，重编码会把 ``/`` 转义成
    ``%2F`` 并补上 ``=``，服务端直接 400。
    """
    kept: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        key = unquote(pair.split("=", 1)[0]).strip().lower()
        if key in RENDITION_QUERY_KEYS or key.startswith(RENDITION_QUERY_PREFIXES):
            continue
        kept.append(pair)
    return "&".join(kept)


def _is_signed_query(query: str) -> bool:
    """查询串里是否带有签名类参数（改一个字符就 401）。"""
    for pair in query.split("&"):
        key = unquote(pair.split("=", 1)[0]).strip().lower()
        if key in SIGNATURE_QUERY_KEYS or key.startswith("x-amz-") or key.startswith("x-goog-"):
            return True
    return False


def upgrade_url(url: str) -> str:
    """尽量把图片地址升级为原始尺寸，并去掉只影响渲染的查询参数。

    带签名的地址只做路径级升级（如微信图床），查询串原样保留。
    """
    parsed = urlparse(url)
    path = parsed.path
    # 微信图床：路径末位是宽度，0 表示原图。
    if "mmbiz.qpic.cn" in (parsed.hostname or ""):
        path = re.sub(r"/\d{2,4}$", "/0", path)
    path = RESIZED_FILENAME.sub("", path)
    query = parsed.query
    if not _is_signed_query(query):
        query = _strip_rendition_query(query)
    return urlunparse(parsed._replace(path=path, query=query))


def normalize_key(url: str) -> str:
    """生成忽略尺寸差异的图片标识，用于同一张图的去重。"""
    parsed = urlparse(upgrade_url(url))
    path = SIZE_TOKEN.sub("", RESIZED_FILENAME.sub("", parsed.path))
    query = _strip_rendition_query(parsed.query)
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def _descriptor_width(descriptor: str) -> int:
    width = WIDTH_DESCRIPTOR.search(descriptor.strip())
    if width:
        return int(width.group(1))
    scale = SCALE_DESCRIPTOR.search(descriptor.strip())
    if scale:
        return int(float(scale.group(1)) * 1_000)
    return 0


def url_width(url: str) -> int:
    """从 URL 推断这张图的渲染宽度，用于在多个尺寸间挑最大的一份。"""
    for pattern in (URL_SIZE_SUFFIX, URL_WIDTH_PARAM, URL_WIDTH_DIRECTORY):
        match = pattern.search(url)
        if match:
            return int(match.group(1))
    return 0


def _srcset_candidates(value: str, base_url: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for item in SRCSET_SPLIT.split(value or ""):
        parts = item.strip().split()
        if not parts:
            continue
        url = absolute_url(parts[0], base_url)
        if url:
            candidates.append(Candidate(url, _descriptor_width(parts[1]) if len(parts) > 1 else 0))
    return candidates


def _is_decorative(image: Any) -> bool:
    """`<img>` 的 alt/class 等属性是否指向头像、图标。"""
    text = " ".join(
        str(image.get(attribute, ""))
        for attribute in ("alt", "class", "id", "data-testid", "aria-label")
    ).lower()
    if not text.strip():
        return False
    return any(re.search(rf"\b{re.escape(marker)}\b", text) for marker in NON_ARTICLE_MARKERS)


def collect_from_html(value: str, base_url: str) -> list[Candidate]:
    """从 HTML（正文片段或整页）收集图片候选。

    同一个 ``<img>`` 的 src/srcset 只是同一张图的不同尺寸，这里直接取声明宽度
    最大的那份，避免同一张图被重复下载。
    """
    soup = BeautifulSoup(value or "", "lxml")
    candidates: list[Candidate] = []
    for image in soup.find_all("img"):
        if _is_decorative(image):
            continue
        declared = 0
        for attribute in ("width", "data-width"):
            try:
                declared = max(declared, int(str(image.get(attribute, "")).strip()))
            except TypeError, ValueError:
                continue
        variants: list[Candidate] = []
        for attribute in (
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
            "data-actualsrc",
            "data-url",
        ):
            url = absolute_url(image.get(attribute), base_url)
            if url:
                variants.append(Candidate(url, declared))
        if image.get("srcset"):
            variants.extend(_srcset_candidates(image.get("srcset", ""), base_url))
        picture = image.find_parent("picture")
        if picture:
            for source in picture.find_all("source"):
                variants.extend(_srcset_candidates(source.get("srcset", ""), base_url))
        if variants:
            best = max(variants, key=lambda candidate: candidate.declared_width)
            if best.declared_width == 0:
                best = Candidate(best.url, url_width(best.url))
            candidates.append(best)

    for meta in soup.find_all("meta", attrs={"property": ("og:image", "og:image:url")}):
        url = absolute_url(meta.get("content"), base_url)
        if url:
            candidates.append(Candidate(url, 1200))
    for meta in soup.find_all("meta", attrs={"name": "twitter:image"}):
        url = absolute_url(meta.get("content"), base_url)
        if url:
            candidates.append(Candidate(url, 600))
    return candidates


def collect_from_rss(entry: Mapping[str, Any], base_url: str) -> list[Candidate]:
    """从 RSS 的 media / enclosure 字段收集图片候选。

    media_content / media_thumbnail 里常常是同一张图的多个尺寸，每个字段只保留
    声明尺寸最大的一份。
    """
    candidates: list[Candidate] = []
    for key in ("media_content", "media_thumbnail"):
        variants: list[Candidate] = []
        for item in entry.get(key) or []:
            url = absolute_url(item.get("url"), base_url)
            if not url:
                continue
            try:
                declared = int(item.get("width") or 0) or int(item.get("height") or 0)
            except TypeError, ValueError:
                declared = 0
            variants.append(Candidate(url, declared or url_width(url)))
        if variants:
            candidates.append(max(variants, key=lambda candidate: candidate.declared_width))
    for enclosure in entry.get("enclosures") or []:
        if str(enclosure.get("type", "")).startswith("image"):
            url = absolute_url(enclosure.get("href") or enclosure.get("url"), base_url)
            if url:
                candidates.append(Candidate(url, url_width(url)))
    return candidates


def rank(candidates: Iterable[Candidate]) -> list[Candidate]:
    """按页面顺序去重：同一张图只保留声明宽度最大的一份。

    返回顺序保持首次出现的位置，这样产物中的图片顺序仍然符合正文阅读顺序。
    """
    best: dict[str, Candidate] = {}
    order: list[str] = []
    for candidate in candidates:
        if not candidate.url or is_non_article(candidate.url):
            continue
        key = normalize_key(candidate.url)
        current = best.get(key)
        if current is None:
            best[key] = candidate
            order.append(key)
        elif candidate.declared_width > current.declared_width:
            best[key] = candidate
    return [best[key] for key in order]


def _fetch_bytes(url: str) -> bytes | None:
    parsed = urlparse(url)
    response = http.get_bytes(
        url,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": f"{parsed.scheme or 'https'}://{parsed.netloc}/",
        },
        stream=True,
    )
    if response is None:
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type and not content_type.startswith("image/"):
        return None
    data = response.content
    return data if data and len(data) <= MAX_IMAGE_BYTES else None


def measure(data: bytes) -> tuple[int, int, str] | None:
    """返回 (宽, 高, 扩展名)，无法识别时返回 None。"""
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            extension = SUPPORTED_FORMATS.get((image.format or "").upper())
    except UnidentifiedImageError, OSError, ValueError:
        return None
    return (width, height, extension) if extension else None


def is_usable(width: int, height: int, size_bytes: int) -> bool:
    """分辨率、宽高比与体积三项同时达标才算正文大图。"""
    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT or size_bytes < MIN_IMAGE_BYTES:
        return False
    aspect = width / height if height else 0
    return MIN_IMAGE_ASPECT <= aspect <= MAX_IMAGE_ASPECT


def download(candidates: Iterable[Candidate], dest_dir: Path, limit: int) -> list[Path]:
    """下载并筛选图片，返回落盘后的文件路径。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    accepted: list[Path] = []
    seen_digest: set[str] = set()
    for candidate in candidates:
        if len(accepted) >= limit:
            break
        data: bytes | None = None
        for url in (upgrade_url(candidate.url), candidate.url):
            data = _fetch_bytes(url)
            if data:
                break
        if not data:
            continue
        measured = measure(data)
        if measured is None:
            continue
        width, height, extension = measured
        if not is_usable(width, height, len(data)):
            LOGGER.debug("跳过低清/非正文图片 %dx%d %s", width, height, candidate.url)
            continue
        digest = hashlib.sha256(data).hexdigest()[:16]
        if digest in seen_digest:
            continue
        seen_digest.add(digest)
        destination = dest_dir / f"{digest}{extension}"
        if not destination.exists():
            destination.write_bytes(data)
        accepted.append(destination)
    return accepted
