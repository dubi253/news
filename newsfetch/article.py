"""单篇文章抓取：请求 → 正文抽取 → 必要时用浏览器渲染重试。

这里的核心是“拿到正文”，因此对同一地址允许多层次升级：

1. requests 取 HTML（http 层已处理拦截、编码与乱码）；
2. trafilatura 抽取正文，过短则按容器兜底；
3. 仍然过短或命中验证页时，用浏览器渲染后再抽一次，取更完整的结果。
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from config import MIN_ARTICLE_CHARS, MIN_IMAGE_HEIGHT, MIN_IMAGE_WIDTH
from newsfetch import browser, dates, extract, http, wechat
from newsfetch.models import Article, Candidate

LOGGER = logging.getLogger("newsfetch.article")
# 短于该长度的正文基本是验证页或占位页残留，直接丢弃。
MIN_USABLE_CHARS = 80
# 页面声明发布时间的 meta 值，按可靠性排序；WordPress 类 CMS 普遍带
# article:published_time，比正文里“x小时前”的相对时间可靠。
PUBLISHED_META_VALUES = frozenset({"article:published_time", "og:article:published_time"})


def _published_from_html(html: str) -> str:
    """从页面的 meta 或 <time> 标签解析发布时间，取不到时返回空串。"""
    soup = BeautifulSoup(html or "", "lxml")
    for meta in soup.find_all("meta"):
        declared = {str(meta.get("property") or "").lower(), str(meta.get("name") or "").lower()}
        if declared & PUBLISHED_META_VALUES:
            parsed = dates.iso_time(meta.get("content"))
            if parsed:
                return parsed
    for tag in soup.find_all("time"):
        parsed = dates.iso_time(tag.get("datetime") or tag.get_text(strip=True))
        if parsed:
            return parsed
    return ""


def _rendered_candidates(page: browser.RenderedPage) -> list[Candidate]:
    """渲染结果中尺寸达标的图片，附带真实宽度作为排序依据。"""
    return [
        Candidate(image.url, image.width)
        for image in page.images
        if image.width >= MIN_IMAGE_WIDTH and image.height >= MIN_IMAGE_HEIGHT
    ]


def fetch(url: str) -> Article:
    """抓取一篇文章；无法使用时返回内容为空的 ``Article``。"""
    if wechat.is_wechat_url(url):
        return wechat.fetch(url)

    page = http.get_page(url)
    if page is None:
        return Article(content="", candidates=(), url=url)

    extracted = extract.extract_html(page.html, page.url)
    content = extracted.content
    candidates = [Candidate(image_url) for image_url in extracted.image_urls]
    # 订阅源不带 pubDate 时（rssbox 镜像等），文章页的声明时间是唯一来源。
    published = _published_from_html(page.html)

    if len(content) < MIN_ARTICLE_CHARS:
        rendered = browser.render(page.url, proxy=http.browser_proxy())
        if rendered is not None:
            rendered_extract = extract.extract_html(rendered.html, rendered.url)
            if len(rendered_extract.content) > len(content):
                content = rendered_extract.content
                candidates = [Candidate(image_url) for image_url in rendered_extract.image_urls]
            candidates.extend(_rendered_candidates(rendered))
            published = published or _published_from_html(rendered.html)

    if (
        len(content) < MIN_USABLE_CHARS
        or extract.looks_like_navigation(content)
        or extract.looks_like_login_wall(content)
    ):
        LOGGER.warning("正文不可用，放弃抓取 %s (%d 字)", url, len(content))
        content = ""
    return Article(content=content, candidates=tuple(candidates), url=page.url, published=published)
