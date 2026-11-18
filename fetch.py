#!/usr/bin/env python3
"""抓取分类新闻，下载正文配图，输出 data/news.json。

用法::

    uv run fetch.py            # 全量抓取
    uv run fetch.py --feed 雷峰 # 只抓来源名包含“雷峰”的订阅源，便于调试
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from config import DATA_DIR, FEEDS, IMAGE_DIR, MAX_ITEMS, OUTPUT_PATH, FeedConfig
from newsfetch import browser, dates
from newsfetch.feeds import fetch_feed

LOGGER = logging.getLogger("newsfetch")


def select_feeds(filters: Sequence[str]) -> tuple[FeedConfig, ...]:
    """按来源名或地址过滤订阅源；为空时返回全部。"""
    if not filters:
        return FEEDS
    return tuple(
        feed
        for feed in FEEDS
        if any(keyword in feed.source or keyword in feed.url for keyword in filters)
    )


def reset_image_dir() -> None:
    """清空旧的图片目录，保证产物与这一轮抓取一致。"""
    if IMAGE_DIR.exists():
        shutil.rmtree(IMAGE_DIR)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def write_snapshot(items: list[dict[str, object]]) -> None:
    """原子地写入 news.json。"""
    payload = {
        "updated": datetime.now(UTC).isoformat(),
        "count": len(items),
        "categories": sorted({str(item["category"]) for item in items}),
        "items": items,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="news-", dir=DATA_DIR, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, OUTPUT_PATH)


def collect(feeds: Sequence[FeedConfig]) -> list[dict[str, object]]:
    """抓取全部订阅源并按链接去重。"""
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for feed in feeds:
        try:
            feed_items = fetch_feed(feed)
        except Exception:  # noqa: BLE001 - 单个源失败不应中断整轮抓取
            LOGGER.exception("订阅源抓取异常: %s", feed.source)
            continue
        for item in feed_items:
            link = str(item["link"])
            if link in seen:
                continue
            seen.add(link)
            items.append(item)
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取分类新闻并下载配图")
    parser.add_argument(
        "--feed",
        action="append",
        default=[],
        metavar="KEYWORD",
        help="只抓取来源名或地址包含该关键字的订阅源，可重复",
    )
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    reset_image_dir()
    try:
        items = collect(select_feeds(args.feed))
    finally:
        browser.close()

    items.sort(key=dates.sort_key, reverse=True)
    items = items[:MAX_ITEMS]
    write_snapshot(items)
    LOGGER.info("写入 %d 条到 %s", len(items), Path(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
