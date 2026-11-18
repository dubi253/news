"""URL 归一化小工具。"""

from __future__ import annotations

import html as html_lib
from typing import Any
from urllib.parse import urljoin, urlparse

SUPPORTED_SCHEMES = ("http://", "https://")


def absolute_url(value: Any, base: str) -> str:
    """把相对地址补全为绝对地址，非 http(s) 一律丢弃。"""
    if not value:
        return ""
    resolved = html_lib.unescape(str(value).strip())
    if resolved.startswith("//"):
        resolved = f"https:{resolved}"
    resolved = urljoin(base, resolved)
    return resolved if resolved.startswith(SUPPORTED_SCHEMES) else ""


def host_of(value: str) -> str:
    """返回小写主机名。"""
    return (urlparse(value).hostname or "").lower()
