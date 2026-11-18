"""微信公众号文章抓取。

策略由弱到强：

1. 复用 ``wechat-article-parser``（纯 HTTP，快）；
2. 回落到带登录态的持久化浏览器（复用 cookie / storage state，人工验证只需做一次）；
3. 判断是否仍停在验证页，避免把“当前环境异常”写进产物。

相关环境变量：
    WECHAT_PROXY                    抓取用的代理
    WECHAT_COOKIE                   导出的 Cookie 串
    WECHAT_STORAGE_STATE            Playwright storage state（JSON 字符串或文件路径）
    WECHAT_BROWSER_PROFILE          持久化用户目录，默认 data/wechat-browser
    WECHAT_HEADFUL                  置 1 时显示浏览器，便于人工过验证
    WECHAT_MANUAL_VERIFY_TIMEOUT    等待人工验证的秒数，默认 120
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from wechat_article_parser import WeChatVerifyError
from wechat_article_parser import parse as parse_wechat_article

from config import (
    MIN_IMAGE_HEIGHT,
    MIN_IMAGE_WIDTH,
    TIMEOUT_SECONDS,
    USER_AGENT,
    WECHAT_PROFILE_DIR,
)
from newsfetch import browser, extract
from newsfetch.images import collect_from_html
from newsfetch.models import Article, Candidate
from newsfetch.text import clean_text
from newsfetch.urls import absolute_url, host_of

LOGGER = logging.getLogger("newsfetch.wechat")
WECHAT_HOST = "mp.weixin.qq.com"
CAPTCHA_PATH = "/mp/wappoc_appmsgcaptcha"
VERIFICATION_MARKERS = ("当前环境异常", "完成验证后即可继续访问", "去验证", "wappoc_appmsgcaptcha")
# 低于该长度视为没拿到正文，继续尝试浏览器路径。
MIN_WECHAT_CHARS = 200
CONTENT_SELECTOR = "#js_content"
HEADLESS_VERIFY_TIMEOUT_MS = 20_000


def is_wechat_url(url: str) -> bool:
    """是否为微信公众号文章域名。"""
    return host_of(url) == WECHAT_HOST


def unwrap_captcha_url(url: str) -> str:
    """把中断在验证页的地址还原成真正的文章地址。"""
    parsed = urlparse(url)
    if host_of(url) != WECHAT_HOST or parsed.path != CAPTCHA_PATH:
        return url
    target = absolute_url(parse_qs(parsed.query).get("target_url", [""])[0], url)
    target_parsed = urlparse(target)
    if host_of(target) == WECHAT_HOST and target_parsed.path.startswith("/s/"):
        return target
    return url


def is_verification_page(url: str, content: str) -> bool:
    """识别没有正文的人机验证页。"""
    if host_of(url) == WECHAT_HOST and urlparse(url).path == CAPTCHA_PATH:
        return True
    text = clean_text(BeautifulSoup(content or "", "lxml").get_text(" ", strip=True))
    return any(marker in text or marker in (content or "") for marker in VERIFICATION_MARKERS)


def article_html(html: str) -> str:
    """取出 ``#js_content`` 正文容器，去掉脚本与页脚。"""
    soup = BeautifulSoup(html or "", "lxml")
    node = soup.select_one(CONTENT_SELECTOR) or soup.find("article") or soup.find("main")
    if node is None:
        return ""
    for tag in node(["script", "style", "noscript", "svg", "form", "nav", "footer", "header"]):
        tag.decompose()
    return str(node)


def parse_cookie_header(value: str) -> list[dict[str, str]]:
    """把导出的 Cookie 串转换成 Playwright 的 cookie 结构。"""
    cookies: list[dict[str, str]] = []
    for item in (value or "").split(";"):
        name, separator, cookie_value = item.strip().partition("=")
        if separator and name:
            cookies.append(
                {"name": name, "value": cookie_value, "domain": ".weixin.qq.com", "path": "/"}
            )
    return cookies


def _storage_state() -> tuple[str | None, str | None]:
    """返回 storage state 路径，以及需要清理的临时文件路径。"""
    value = os.getenv("WECHAT_STORAGE_STATE", "").strip()
    if not value:
        return None, None
    if value.startswith("{"):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="wechat-storage-", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(value)
            temporary_path = handle.name
        return temporary_path, temporary_path
    if os.path.isfile(value):
        return value, None
    LOGGER.warning("WECHAT_STORAGE_STATE 指向的文件不存在: %s", value)
    return None, None


def _manual_verify_timeout() -> int:
    try:
        return max(10, int(os.getenv("WECHAT_MANUAL_VERIFY_TIMEOUT", "120")))
    except ValueError:
        return 120


def _with_parser(link: str) -> Article | None:
    """用开源解析库直接取正文。"""
    try:
        result = parse_wechat_article(
            link,
            timeout=TIMEOUT_SECONDS,
            user_agent=USER_AGENT,
            proxy=os.getenv("WECHAT_PROXY", "").strip() or None,
        )
    except WeChatVerifyError:
        LOGGER.info("微信人机验证页，改用浏览器: %s", link)
        return None
    except (httpx.HTTPError, TimeoutError, OSError, TypeError, ValueError) as exc:
        LOGGER.warning("微信解析库失败 %s: %s", link, exc)
        return None

    if not result.is_valid or not result.article_markdown:
        return None
    content, inline_images = extract.split_images(result.article_markdown)
    urls = list(dict.fromkeys([*result.images, *inline_images]))
    return Article(content=content, candidates=tuple(Candidate(url) for url in urls), url=link)


def _with_browser(link: str) -> Article | None:
    """带登录态的浏览器兜底。"""
    headful = os.getenv("WECHAT_HEADFUL", "").strip().lower() in {"1", "true", "yes"}
    profile = os.getenv("WECHAT_BROWSER_PROFILE", "").strip() or str(WECHAT_PROFILE_DIR)
    Path(profile).mkdir(parents=True, exist_ok=True)
    storage_state, temporary_state = _storage_state()
    # 只有可见浏览器才有人能过验证；headless 下等太久只是浪费时间。
    wait_ms = _manual_verify_timeout() * 1_000 if headful else HEADLESS_VERIFY_TIMEOUT_MS
    try:
        page = browser.render_persistent(
            link,
            profile,
            cookies=parse_cookie_header(os.getenv("WECHAT_COOKIE", "")),
            storage_state=storage_state,
            headless=not headful,
            wait_for_selector=CONTENT_SELECTOR,
            wait_ms=wait_ms,
            proxy=os.getenv("WECHAT_PROXY", "").strip() or None,
            extra_http_headers={"Referer": f"https://{WECHAT_HOST}/"},
        )
    finally:
        if temporary_state:
            try:
                os.unlink(temporary_state)
            except OSError:
                LOGGER.warning("无法删除临时 storage state: %s", temporary_state)

    if page is None:
        return None
    resolved = unwrap_captcha_url(page.url)
    if is_verification_page(resolved, page.html):
        LOGGER.warning("仍停留在微信人机验证页，放弃正文: %s", link)
        return None
    container = article_html(page.html)
    content = extract.fragment_to_markdown(container)
    candidates = list(collect_from_html(container, resolved))
    candidates += [
        Candidate(image.url, image.width)
        for image in page.images
        if image.width >= MIN_IMAGE_WIDTH and image.height >= MIN_IMAGE_HEIGHT
    ]
    return Article(content=content, candidates=tuple(candidates), url=resolved)


def fetch(url: str) -> Article:
    """抓取一篇公众号文章，取两条路径中正文更完整的结果。"""
    link = unwrap_captcha_url(url)
    parsed = _with_parser(link)
    if parsed is not None and len(parsed.content) >= MIN_WECHAT_CHARS:
        return parsed

    rendered = _with_browser(link)
    if rendered is not None and (parsed is None or len(rendered.content) > len(parsed.content)):
        return rendered
    return parsed or rendered or Article(content="", candidates=(), url=link)
