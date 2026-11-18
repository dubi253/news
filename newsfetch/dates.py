"""订阅源时间戳解析。

区分两类情况：

* 订阅源给出正确的时区偏移：保留偏移，不猜测。
* 订阅源把本地时间标成 UTC/GMT（InfoQ 等）：由 ``FeedConfig.timezone``
  指定墙上时区，忽略其声明的偏移。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATE_KEYS = ("published", "updated", "date", "created", "issued")
PARSED_KEYS = (
    "published_parsed",
    "updated_parsed",
    "date_parsed",
    "created_parsed",
    "issued_parsed",
)


def _parse_string(value: str) -> datetime | None:
    """把 RSS 中的时间字符串解析为 datetime，解析失败返回 None。"""
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except TypeError, ValueError:
        return None


def _parse_struct(value: Any) -> datetime:
    """feedparser 的 *_parsed 字段已被归一化为 UTC 的结构体。"""
    return datetime(*value[:6], tzinfo=UTC)


def iso_time(value: Any, wall_clock_zone: str | None = None) -> str:
    """返回 ISO 8601 时间，无法判断时区时返回空串。

    Args:
        value: RSS 时间字符串或 feedparser 的 struct_time。
        wall_clock_zone: 指定后，把时间字符串的墙上时间视为该时区，
            并忽略字符串自带的偏移。
    """
    if not value:
        return ""
    try:
        zone = ZoneInfo(wall_clock_zone) if wall_clock_zone else None
        if hasattr(value, "tm_year"):
            parsed = _parse_struct(value)
            if zone:
                parsed = parsed.astimezone(zone)
            return parsed.isoformat()

        parsed = _parse_string(str(value))
        if parsed is None:
            return ""
        if zone:
            # 发布方混淆了本地时间与 GMT，以配置的墙上时区为准。
            parsed = parsed.replace(tzinfo=None).replace(tzinfo=zone)
        elif parsed.tzinfo is None:
            return ""
        return parsed.isoformat()
    except TypeError, ValueError, OverflowError, ZoneInfoNotFoundError:
        return ""


def published_time(entry: Mapping[str, Any], wall_clock_zone: str | None = None) -> str:
    """从条目中取出第一个可用的发布时间。"""
    for key in DATE_KEYS:
        if entry.get(key):
            parsed = iso_time(entry[key], wall_clock_zone)
            if parsed:
                return parsed
    for key in PARSED_KEYS:
        if entry.get(key):
            parsed = iso_time(entry[key], wall_clock_zone)
            if parsed:
                return parsed
    return ""


def sort_key(item: Mapping[str, Any]) -> float:
    """按真实时刻排序，屏蔽各源时区标注不一致的影响。"""
    published = item.get("published")
    if not published:
        return 0.0
    try:
        return datetime.fromisoformat(str(published)).timestamp()
    except TypeError, ValueError, OverflowError:
        return 0.0
