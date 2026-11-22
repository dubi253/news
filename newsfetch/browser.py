"""Playwright 渲染层。

被拦截或需要 JS 才能出正文的页面走这里。整轮抓取共用一个 Chromium 实例，
避免“每篇文章启动一次浏览器”的开销。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from config import BROWSER_TIMEOUT_MS, USER_AGENT

LOGGER = logging.getLogger("newsfetch.browser")
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "enable javascript and cookies",
    "cf-browser-verification",
    "verify you are human",
    "人机验证",
    "安全验证",
    "访问验证",
)


@dataclass(frozen=True, slots=True)
class ImageRef:
    """渲染后 DOM 中一张图片的真实尺寸。"""

    url: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """浏览器渲染结果。"""

    url: str
    html: str
    images: tuple[ImageRef, ...]
    blocked: bool


_LOCAL = threading.local()
# 并发抓取时每个线程各自持有一个 Chromium（sync API 不能跨线程共享），
# 这里登记全部实例，进程退出时统一回收。
_INSTANCES: list[tuple[Any, Any]] = []
_INSTANCES_LOCK = threading.Lock()
_IMAGE_SCRIPT = """
() => Array.from(document.images).map((img) => ({
  url: img.currentSrc || img.src || '',
  width: img.naturalWidth || 0,
  height: img.naturalHeight || 0,
}))
"""


def available() -> bool:
    """Playwright 是否安装可用。"""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _shared_browser() -> Any:
    """惰性启动并复用当前线程的 Chromium。"""
    browser = getattr(_LOCAL, "browser", None)
    if browser is not None:
        return browser
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=True,
        args=["--disable-http2", "--disable-dev-shm-usage"],
    )
    _LOCAL.playwright = playwright
    _LOCAL.browser = browser
    with _INSTANCES_LOCK:
        _INSTANCES.append((playwright, browser))
    return browser


def _collect_images(page: Any) -> tuple[ImageRef, ...]:
    raw = page.evaluate(_IMAGE_SCRIPT)
    return tuple(
        ImageRef(
            str(item.get("url", "")), int(item.get("width") or 0), int(item.get("height") or 0)
        )
        for item in raw
        if item.get("url")
    )


def _is_challenge(html: str, title: str) -> bool:
    haystack = f"{title}\n{html[:20_000]}".lower()
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


def _settle(page: Any, wait_ms: int, wait_for_selector: str | None) -> None:
    """等待水合完成，并滚动触发懒加载图片。"""
    if wait_for_selector:
        try:
            page.wait_for_selector(wait_for_selector, state="attached", timeout=wait_ms)
        except Exception:  # noqa: BLE001 - 超时也继续，交给上层判断正文长度
            LOGGER.debug("selector %s not found in time", wait_for_selector)
    else:
        page.wait_for_timeout(wait_ms)
    try:
        page.evaluate(
            """
            async () => {
              const step = Math.max(window.innerHeight, 600);
              for (let y = 0; y < document.body.scrollHeight; y += step) {
                window.scrollTo(0, y);
                await new Promise((resolve) => setTimeout(resolve, 120));
              }
              window.scrollTo(0, 0);
            }
            """
        )
    except Exception:  # noqa: BLE001 - 滚动失败不影响正文
        LOGGER.debug("scroll for lazy images failed")


def _read_page(page: Any, blocked_probe: bool = True) -> RenderedPage:
    html = page.content()
    title = ""
    with contextlib.suppress(Exception):
        title = page.title()
    return RenderedPage(
        url=page.url,
        html=html,
        images=_collect_images(page),
        blocked=blocked_probe and _is_challenge(html, title),
    )


def render(
    url: str,
    *,
    wait_for_selector: str | None = None,
    wait_ms: int = 1_500,
    timeout_ms: int = BROWSER_TIMEOUT_MS,
    proxy: str | None = None,
) -> RenderedPage | None:
    """用共享浏览器渲染页面，失败返回 None。"""
    if not available():
        LOGGER.warning("Playwright 不可用，跳过浏览器渲染: %s", url)
        return None
    from playwright.sync_api import Error as PlaywrightError

    try:
        browser = _shared_browser()
        options: dict[str, Any] = {
            "user_agent": USER_AGENT,
            "locale": "zh-CN",
            "viewport": {"width": 1440, "height": 900},
        }
        if proxy:
            options["proxy"] = {"server": proxy}
        context = browser.new_context(**options)
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            _settle(page, wait_ms, wait_for_selector)
            return _read_page(page)
        finally:
            context.close()
    except PlaywrightError as exc:
        LOGGER.warning("浏览器渲染失败 %s: %s", url, exc)
        return None


def render_persistent(
    url: str,
    profile_dir: str,
    *,
    cookies: Sequence[dict[str, Any]] = (),
    storage_state: str | None = None,
    headless: bool = True,
    wait_for_selector: str | None = None,
    wait_ms: int = 20_000,
    timeout_ms: int = BROWSER_TIMEOUT_MS,
    proxy: str | None = None,
    extra_http_headers: dict[str, str] | None = None,
) -> RenderedPage | None:
    """用持久化用户目录渲染（微信公众号等需要登录态的站点）。"""
    if not available():
        return None
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    launch_options: dict[str, Any] = {
        "headless": headless,
        "args": ["--disable-http2", "--disable-dev-shm-usage"],
        "user_agent": USER_AGENT,
        "locale": "zh-CN",
        "viewport": {"width": 1440, "height": 900},
    }
    if proxy:
        launch_options["proxy"] = {"server": proxy}
    if storage_state:
        launch_options["storage_state"] = storage_state

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(profile_dir, **launch_options)
            try:
                if cookies:
                    context.add_cookies(list(cookies))
                page = context.pages[0] if context.pages else context.new_page()
                if extra_http_headers:
                    page.set_extra_http_headers(extra_http_headers)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                _settle(page, wait_ms, wait_for_selector)
                return _read_page(page)
            finally:
                context.close()
    except (PlaywrightError, OSError) as exc:
        LOGGER.warning("浏览器渲染失败 %s: %s", url, exc)
        return None


def close() -> None:
    """释放所有线程的共享浏览器；进程退出前调用一次即可。"""
    with _INSTANCES_LOCK:
        instances = list(_INSTANCES)
        _INSTANCES.clear()
    for playwright, browser in instances:
        try:
            browser.close()
        except Exception:  # noqa: BLE001 - 退出阶段无需处理
            LOGGER.debug("close browser failed")
        try:
            playwright.stop()
        except Exception:  # noqa: BLE001
            LOGGER.debug("stop playwright failed")
    _LOCAL.browser = None
    _LOCAL.playwright = None
