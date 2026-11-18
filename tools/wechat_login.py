#!/usr/bin/env python3
"""在带图形界面的机器上获取微信公众号会话，供 CI 使用。

微信公众号对数据中心 IP 很敏感，CI 上经常被拦到 ``wappoc_appmsgcaptcha`` 验证页。
这个脚本用可见的浏览器打开页面，由人工完成验证/登录，然后把会话导出成
Playwright 的 storage state，作为 ``WECHAT_STORAGE_STATE`` 机密写进仓库。

用法::

    uv run python tools/wechat_login.py
    uv run python tools/wechat_login.py --article https://mp.weixin.qq.com/s/xxxx

产物（均在 data/ 下，已被 .gitignore 忽略，不会进仓库）::

    data/wechat-storage.json   会话状态，给 WECHAT_STORAGE_STATE
    data/wechat-cookie.txt     Cookie 头，给 WECHAT_COOKIE

提示：会话与出口 IP 绑定，换网络（代理/机房）后通常需要重新获取。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import USER_AGENT, WECHAT_PROFILE_DIR  # noqa: E402
from newsfetch.wechat import CONTENT_SELECTOR, is_verification_page  # noqa: E402

HOME_URL = "https://mp.weixin.qq.com/"
STORAGE_PATH = Path("data/wechat-storage.json")
COOKIE_PATH = Path("data/wechat-cookie.txt")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="获取微信公众号会话（storage state）")
    parser.add_argument(
        "--article",
        default="",
        metavar="URL",
        help="用于验证的公众号文章地址；不给则只打开公众号首页",
    )
    parser.add_argument(
        "--profile",
        default=str(WECHAT_PROFILE_DIR),
        help="持久化用户目录（复用其中的既有登录态）",
    )
    parser.add_argument("--output", default=str(STORAGE_PATH), help="storage state 输出路径")
    parser.add_argument("--cookie-output", default=str(COOKIE_PATH), help="Cookie 头输出路径")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="等待人工完成验证的秒数，默认 300",
    )
    return parser.parse_args()


def _cookie_header(cookies: list[dict]) -> str:
    """把 Playwright 的 cookie 列表拼成可直接塞进环境变量的 Cookie 头。"""
    pairs = [
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if "weixin" in cookie.get("domain", "")
    ]
    return "; ".join(dict.fromkeys(pairs))


def _wait_for_article(page, article_url: str, timeout: int) -> bool:
    """轮询到出现正文容器、或验证页消失为止。"""
    deadline = time.monotonic() + timeout
    last_state = ""
    while time.monotonic() < deadline:
        try:
            state = page.evaluate(
                """(selector) => {
                    const node = document.querySelector(selector);
                    if (node && node.innerText.trim().length > 200) return 'ok';
                    return document.body ? document.body.innerText.slice(0, 80) : '';
                }""",
                CONTENT_SELECTOR,
            )
        except Exception:  # noqa: BLE001 - 页面跳转期间 evaluate 可能失败
            state = ""
        if state == "ok":
            return True
        if article_url and is_verification_page(page.url, page.content()):
            state = "等待人工完成验证"
        if state != last_state:
            print(f"  ... {state or '页面加载中'}")
            last_state = state
        page.wait_for_timeout(2_000)
    return False


def main() -> int:
    args = _parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 Playwright：uv sync && uv run playwright install chromium", file=sys.stderr)
        return 1

    profile = Path(args.profile)
    profile.mkdir(parents=True, exist_ok=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"打开浏览器（用户目录 {profile}）")
    print("如果是第一次使用：窗口里完成滑动验证即可，公众号文章本身无需登录。")
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                headless=False,
                user_agent=USER_AGENT,
                locale="zh-CN",
                viewport={"width": 1280, "height": 900},
            )
        except Exception as exc:  # noqa: BLE001 - 无图形界面时明确提示
            print(f"浏览器启动失败：{exc}", file=sys.stderr)
            print("需要图形界面；纯命令行主机可先安装 xvfb 并设置 DISPLAY。", file=sys.stderr)
            return 1

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.article or HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            if args.article:
                print(f"等待正文出现（最长 {args.timeout} 秒）")
                ok = _wait_for_article(page, args.article, args.timeout)
                print("正文已就绪" if ok else "超时未拿到正文，仍会导出当前会话")
            else:
                print("在窗口里完成验证后按回车继续")
                input()

            context.storage_state(path=str(output))
            cookies = context.cookies()
        finally:
            context.close()

    header = _cookie_header(cookies)
    Path(args.cookie_output).write_text(header, encoding="utf-8")
    print(f"\n已写入 {output}（{output.stat().st_size} 字节）")
    print(f"已写入 {args.cookie_output}（{len(header)} 字节）")
    print("\n写入 GitHub 机密（在仓库目录执行）：")
    print(f"  gh secret set WECHAT_STORAGE_STATE < {output}")
    print(f"  gh secret set WECHAT_COOKIE < {args.cookie_output}")
    print("\n两者任选其一即可；storage state 更完整，Cookie 头只在需要时用。")
    print("这些凭据等同于你的微信网页会话，不要提交进仓库或贴到聊天里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
