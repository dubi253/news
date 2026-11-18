"""正文提取：以 trafilatura 为主，BeautifulSoup + markdownify 兜底。

产物的 ``content`` 是纯文本 Markdown（不含图片），图片统一放到 ``images``，
因此这里会把正文中的图片链接抽出来单独返回。
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass

import trafilatura
from bs4 import BeautifulSoup
from markdownify import markdownify

from config import MAX_CONTENT_LENGTH, MIN_ARTICLE_CHARS
from newsfetch.text import clean_text, normalize_markdown

LOGGER = logging.getLogger("newsfetch.extract")
# trafilatura 对“抽不到正文”的页面会打 WARNING，而我们随后会用浏览器重试，
# 这类噪声没有诊断价值。
logging.getLogger("trafilatura").setLevel(logging.ERROR)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
CONTENT_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    "#js_content",
    ".rich_media_content",
    ".article-content",
    ".article_con",
    ".post-content",
    ".entry-content",
    ".content",
    "#content",
)
READ_MORE_MARKERS = re.compile(
    r"\b(?:read\s+more|continue\s+reading|read\s+the\s+full)\b|阅读全文|继续阅读|查看全文",
    re.IGNORECASE,
)
STRIP_TAGS = ("script", "style", "noscript", "svg", "form", "nav", "footer", "header", "aside")
# 登录墙 / 验证页的典型文案，命中说明没拿到正文。
LOGIN_WALL_MARKERS = (
    "扫描二维码登录",
    "登录/注册",
    "请登录后查看",
    "请先登录",
    "sign in to continue",
    "subscribe to continue",
    "create a free account",
    "enable javascript and cookies",
    "访问验证",
)


@dataclass(frozen=True, slots=True)
class Extracted:
    """正文抽取结果。"""

    content: str
    image_urls: tuple[str, ...]
    truncated: bool


def split_images(markdown: str) -> tuple[str, tuple[str, ...]]:
    """把 Markdown 中的图片语法剥离，返回纯文本与图片地址。"""
    urls = tuple(dict.fromkeys(MARKDOWN_IMAGE.findall(markdown or "")))
    text = MARKDOWN_IMAGE.sub("", markdown or "")
    return normalize_markdown(text, MAX_CONTENT_LENGTH), urls


def has_read_more_marker(value: str) -> bool:
    """RSS 摘要里是否明确出现“阅读更多”之类的截断标记。"""
    if not value:
        return False
    soup = BeautifulSoup(html_lib.unescape(value), "lxml")
    labels = " ".join(
        clean_text(node.get_text(" ", strip=True)) for node in soup.find_all(["a", "button"])
    )
    return bool(READ_MORE_MARKERS.search(f"{labels} {clean_text(soup.get_text(' ', strip=True))}"))


def _clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(list(STRIP_TAGS)):
        tag.decompose()
    return soup


def _container_html(html: str) -> str:
    """按常见正文容器选择器挑出正文 HTML。"""
    soup = _clean_soup(BeautifulSoup(html or "", "lxml"))
    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) >= MIN_ARTICLE_CHARS // 2:
            return str(node)
    body = soup.body or soup
    return str(body)


def fragment_to_markdown(value: str) -> str:
    """把 RSS 摘要等 HTML 片段转成 Markdown（不套正文容器）。"""
    if not value:
        return ""
    soup = _clean_soup(BeautifulSoup(html_lib.unescape(value), "lxml"))
    markdown = markdownify(str(soup), heading_style="ATX", bullets="-", strip=["img"])
    return normalize_markdown(markdown, MAX_CONTENT_LENGTH)


def _trafilatura_markdown(html: str, url: str) -> str:
    try:
        markdown = trafilatura.extract(
            html,
            url=url or None,
            output_format="markdown",
            include_images=True,
            include_links=False,
            include_comments=False,
            include_tables=False,
            deduplicate=True,
            favor_recall=True,
        )
    except Exception as exc:  # noqa: BLE001 - 抽取库对畸形页面可能抛任意异常
        LOGGER.warning("trafilatura 提取失败 %s: %s", url, exc)
        return ""
    return markdown or ""


def extract_html(html: str, url: str = "") -> Extracted:
    """从完整页面 HTML 中抽取正文、图片与截断标记。

    Args:
        html: 页面 HTML（已按正确编码解码）。
        url: 页面地址，供抽取库解析相对链接。

    Returns:
        ``Extracted``；正文过短时按容器兜底再试一次。
    """
    markdown = _trafilatura_markdown(html, url)
    if len(markdown) < MIN_ARTICLE_CHARS:
        fallback = fragment_to_markdown(_container_html(html))
        if len(fallback) > len(markdown):
            markdown = fallback
    content, images = split_images(markdown)
    return Extracted(
        content=content,
        image_urls=images,
        truncated=has_read_more_marker(html),
    )


def looks_like_login_wall(content: str) -> bool:
    """判断正文是否来自登录墙/验证页而非文章。

    命中登录页常见文案且整体很短，说明正文根本没拿到，写进产物只会误导读者。
    """
    if not content or len(content) >= MIN_ARTICLE_CHARS:
        return False
    return any(marker in content for marker in LOGIN_WALL_MARKERS)


def looks_like_navigation(content: str) -> bool:
    """判断正文是否只是导航/菜单碎片。

    真实稿件的段落普遍较长；只有“首页”“资讯”这类短行且整体不足
    ``MIN_ARTICLE_CHARS`` 时，基本可以判定抽取失败（常见于 SPA 外壳页）。
    """
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines or len(content) >= MIN_ARTICLE_CHARS:
        return False
    return max(len(line) for line in lines) < 40
