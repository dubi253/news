"""HTTP 访问层：统一会话、拦截识别与浏览器升级。

请求优先走 requests；遇到反爬状态码、验证页或近乎空的 HTML 时，升级到
Playwright 渲染后再返回，调用方无需关心具体的拦截手段。
"""

from __future__ import annotations

import logging
import os
import random
import time
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
# 可以再等一会儿的状态码：服务端临时故障或限流，重试往往能过。
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# 应用层重试的退避：首轮等待较短，之后翻倍；抖动让同时失败的订阅源错开重试。
RETRY_BASE_SECONDS = 3.0
RETRY_MAX_SECONDS = 30.0


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


def _retryable(exc: requests.RequestException) -> bool:
    """该异常是否值得重试。

    4xx 里只有 429 值得再等；连接中断、超时、分块编码错误都属于网络抖动。
    """
    status = getattr(exc.response, "status_code", None)
    if status is not None:
        return status in RETRYABLE_STATUS
    return isinstance(
        exc,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _retry_delay(attempt: int) -> float:
    """第 ``attempt`` 次失败后的等待秒数：指数退避加抖动，且不超过上限。"""
    delay = min(RETRY_BASE_SECONDS * 2 ** (attempt - 1), RETRY_MAX_SECONDS)
    return random.uniform(delay / 2, delay)


def get_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: int = TIMEOUT_SECONDS,
    stream: bool = False,
    attempts: int = 1,
) -> requests.Response | None:
    """GET 请求，失败返回 None（仅记录日志，不抛出）。

    Args:
        url: 目标地址。
        headers: 附加请求头。
        timeout: 单次请求的超时秒数。
        stream: 是否流式读取响应体（下载图片用）。
        attempts: 最多请求次数（含首次）。状态码可重试或网络异常时才继续，
            按指数退避等待；默认只请求一次，交给调用方决定是否值得等待。

    Returns:
        成功的响应；重试用尽或遇到不可重试的错误时返回 None。
    """
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        try:
            response = _SESSION.get(
                url, headers=dict(headers or {}), timeout=timeout, stream=stream
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if attempt >= total or not _retryable(exc):
                LOGGER.warning("请求失败 %s: %s", url, exc)
                return None
            delay = _retry_delay(attempt)
            LOGGER.info(
                "请求失败 %s: %s；%.1f 秒后重试（第 %d/%d 次）",
                url,
                exc,
                delay,
                attempt + 1,
                total,
            )
            time.sleep(delay)
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
