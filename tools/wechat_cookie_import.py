#!/usr/bin/env python3
"""把浏览器里导出的微信 cookie 转成 Playwright storage state。

适用场景：抓取主机没有图形界面（SSH），无法在主机上弹出浏览器过验证。
在**自己的电脑**浏览器里打开文章、完成验证后，用扩展（如 Cookie-Editor）
导出 mp.weixin.qq.com 的 cookie，再用本脚本转换并当场验证是否可用。

用法::

    # Cookie-Editor 导出的 JSON 数组
    uv run python tools/wechat_cookie_import.py --cookie-json cookies.json \\
        --article https://mp.weixin.qq.com/s/xxxx

    # 或者直接给一行 Cookie 头（注意 HttpOnly 的条目扩展才能导出）
    uv run python tools/wechat_cookie_import.py \\
        --cookie-header "wxuin=123; wxsid=abc; pass_ticket=xyz"

产物 ``data/wechat-storage.json`` 直接作为 ``WECHAT_STORAGE_STATE`` 使用。

注意：cookie 与出口 IP 绑定，验证要在哪台机器上抓取，就用哪台机器的网络导出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from config import BASE_DIR, HEADERS, TIMEOUT_SECONDS  # noqa: E402

HOST_SUFFIX = "weixin.qq.com"
# 微信的会话 cookie 有一部分挂在 .qq.com 上（如 wxuin），一并保留。
ALLOWED_DOMAIN_SUFFIXES = ("qq.com", "weixin.qq.com")
DEFAULT_OUTPUT = "data/wechat-storage.json"


def parse_cookie_json(raw: str) -> list[dict[str, object]]:
    """解析 Cookie-Editor / 浏览器扩展导出的 JSON，兼容数组与 name-value 字典。"""
    payload = json.loads(raw)
    if isinstance(payload, dict) and "cookies" in payload:
        payload = payload["cookies"]
    if isinstance(payload, dict):
        payload = [{"name": key, "value": value} for key, value in payload.items()]
    if not isinstance(payload, list):
        raise ValueError("cookie JSON 结构无法识别")

    cookies: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "").strip() or f".{HOST_SUFFIX}"
        if not name or not domain.endswith(ALLOWED_DOMAIN_SUFFIXES):
            continue
        cookie: dict[str, object] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": str(item.get("path") or "/"),
            "expires": float(item.get("expirationDate") or item.get("expires") or -1),
            "httpOnly": bool(item.get("httpOnly", False)),
            "secure": bool(item.get("secure", True)),
            "sameSite": item.get("sameSite") or "Lax",
        }
        cookies.append(cookie)
    return cookies


def parse_cookie_header(header: str) -> list[dict[str, object]]:
    """把 ``a=b; c=d`` 形式的 Cookie 头转成 cookie 列表。"""
    cookies: list[dict[str, object]] = []
    for item in header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name:
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": f".{HOST_SUFFIX}",
                    "path": "/",
                    "expires": -1.0,
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )
    return cookies


def verify(article: str, cookies: list[dict[str, object]]) -> bool:
    """用 cookie 请求文章，判断是否已经绕过验证页。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["Referer"] = "https://mp.weixin.qq.com/"
    for cookie in cookies:
        session.cookies.set(str(cookie["name"]), str(cookie["value"]), domain=HOST_SUFFIX, path="/")
    response = session.get(article, timeout=TIMEOUT_SECONDS)
    ok = "#js_content" in response.text
    print(
        f"验证请求 status={response.status_code} len={len(response.text)} 正文={'拿到' if ok else '没有'}"
    )
    if not ok:
        print("提示：如果仍然停在验证页，说明 cookie 与当前网络出口不匹配，")
        print("      请在本机浏览器中过验证后重新导出（或在浏览器里确认文章能正常打开）。")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="导入微信 cookie 并生成 storage state")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cookie-json", metavar="FILE", help="扩展导出的 cookie JSON 文件")
    source.add_argument("--cookie-header", metavar="STRING", help="Cookie 头字符串")
    parser.add_argument("--article", default="", metavar="URL", help="用于验证的文章地址")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="storage state 输出路径")
    parser.add_argument("--no-verify", action="store_true", help="只转换，不发请求验证")
    args = parser.parse_args()

    if args.cookie_json:
        raw = Path(args.cookie_json).read_text(encoding="utf-8")
        cookies = parse_cookie_json(raw)
    else:
        cookies = parse_cookie_header(args.cookie_header or "")

    if not cookies:
        print("没有解析到 mp.weixin.qq.com 的 cookie", file=sys.stderr)
        return 1

    output = Path(args.output)
    if not output.is_absolute():
        output = BASE_DIR / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False), encoding="utf-8"
    )
    print(f"已写入 {output}（{len(cookies)} 条 cookie）")

    verified = True if args.no_verify else bool(args.article and verify(args.article, cookies))
    print("\n使用方式：")
    print(f"  gh secret set WECHAT_STORAGE_STATE < {output}")
    print(
        f"  # 本地调试：WECHAT_STORAGE_STATE={output} uv run python fetch.py --feed 半导体行业观察"
    )
    print("这些 cookie 等同于你的微信网页会话，不要提交进仓库或贴到聊天里。")
    return 0 if verified or args.no_verify else 2


if __name__ == "__main__":
    raise SystemExit(main())
