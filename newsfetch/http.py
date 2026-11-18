"""HTTP 访问层：统一会话、拦截识别与浏览器升级。

请求优先走 requests；遇到反爬状态码、验证页或近乎空的 HTML 时，升级到
Playwright 渲染后再返回，调用方无需关心具体的拦截手段。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import HEADERS, TIMEOUT_SECONDS
from newsfetch import browser
from newsfetch.text import decode_body

LOGGER = logging.getLogger("newsfetch.http")
BLOCKED_STATUS = frozenset({401, 403, 407, 429, 451, 503})
BLOCKED_MARKERS = (
    "just a moment",
    "attention required",
    "cf-browser-verification",
    "challenge-platform",
    "verify you are human",
    "access denied",
    "request blocked",
    "请完成安全验证",
    "当前环境异常",
    "访问过于频繁",
    "人机验证",
    "安全验证",
)
# 低于该长度的 HTML 基本不可能是正文页。
MIN_PAGE_HTML = 1_500


@dataclass(frozen=True, slots=True)
class Page:
    """一次页面访问的结果。"""

    url: str
    html: str
    status: int
    rendered: bool
    blocked: bool


def browser_proxy() -> str | None:
    """浏览器不读环境的代理变量，这里显式取一次。"""
    for name in ("NEWS_BROWSER_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def session() -> requests.Session:
    """返回全局复用的 requests 会话。"""
    return _SESSION


def get_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: int = TIMEOUT_SECONDS,
    stream: bool = False,
) -> requests.Response | None:
    """GET 请求，失败返回 None（仅记录日志，不抛出）。"""
    try:
        response = _SESSION.get(url, headers=dict(headers or {}), timeout=timeout, stream=stream)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        LOGGER.warning("请求失败 %s: %s", url, exc)
        return None


def looks_blocked(status: int, text: str) -> bool:
    """判断响应是否为人机验证/反爬页面。"""
    if status in BLOCKED_STATUS:
        return True
    haystack = (text or "")[:20_000].lower()
    return any(marker in haystack for marker in BLOCKED_MARKERS)


def _render(url: str) -> Page | None:
    rendered = browser.render(url, proxy=browser_proxy())
    if rendered is None:
        return None
    return Page(
        url=rendered.url,
        html=rendered.html,
        status=200,
        rendered=True,
        blocked=rendered.blocked,
    )


def get_page(url: str, *, allow_browser: bool = True) -> Page | None:
    """取页面 HTML，必要时用浏览器渲染。

    Args:
        url: 目标地址。
        allow_browser: 是否允许升级到 Playwright。

    Returns:
        页面结果；普通请求与浏览器渲染都失败时返回 None。
    """
    response: requests.Response | None = None
    try:
        response = _SESSION.get(url, timeout=TIMEOUT_SECONDS)
        text = decode_body(response.content, response.headers)
    except requests.RequestException as exc:
        LOGGER.warning("请求失败 %s: %s", url, exc)
        text = ""

    if response is not None:
        blocked = looks_blocked(response.status_code, text)
        if not blocked and response.ok and len(text) >= MIN_PAGE_HTML:
            return Page(
                url=response.url,
                html=text,
                status=response.status_code,
                rendered=False,
                blocked=False,
            )
        LOGGER.info(
            "升级浏览器渲染 %s (status=%s, blocked=%s, len=%d)",
            url,
            response.status_code,
            blocked,
            len(text),
        )

    if allow_browser:
        rendered_page = _render(url)
        if rendered_page is not None:
            return rendered_page

    if response is None or not response.ok:
        return None
    return Page(
        url=response.url,
        html=text,
        status=response.status_code,
        rendered=False,
        blocked=looks_blocked(response.status_code, text),
    )
