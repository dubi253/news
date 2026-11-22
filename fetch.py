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

from config import (
    DATA_DIR,
    FEEDS,
    IMAGE_DIR,
    MAX_ITEMS,
    MIN_PUBLISH_ITEMS,
    OUTPUT_PATH,
    REPORT_PATH,
    FeedConfig,
)
from newsfetch import browser, dates
from newsfetch.feeds import fetch_feed
from newsfetch.models import NewsItem
from newsfetch.report import FeedStats as ReportFeedStats
from newsfetch.report import write_report

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


def write_snapshot(items: Sequence[NewsItem]) -> None:
    """原子地写入 news.json。"""
    payload = {
        "updated": datetime.now(UTC).isoformat(),
        "count": len(items),
        "categories": sorted({item["category"] for item in items}),
        "items": items,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="news-", dir=DATA_DIR, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, OUTPUT_PATH)


def collect(feeds: Sequence[FeedConfig]) -> tuple[list[NewsItem], dict[str, str]]:
    """抓取全部订阅源并按链接去重。

    Returns:
        去重后的条目，以及抓取失败的订阅源到异常简述的映射。
    """
    items: list[NewsItem] = []
    seen: set[str] = set()
    errors: dict[str, str] = {}
    for feed in feeds:
        try:
            feed_items = fetch_feed(feed)
        except Exception as exc:
            # 订阅源互相独立：单个源的任何失败都不应中断整轮抓取，
            # LOGGER.exception 记录完整堆栈便于事后定位。
            LOGGER.exception("订阅源抓取异常: %s", feed.source)
            errors[feed.source] = f"{type(exc).__name__}: {exc}"
            continue
        for item in feed_items:
            link = str(item["link"])
            if link in seen:
                continue
            seen.add(link)
            items.append(item)
    return items, errors


def summarize(
    feeds: Sequence[FeedConfig], items: Sequence[NewsItem], errors: dict[str, str]
) -> list[ReportFeedStats]:
    """按订阅源统计本轮最终入产物的条目质量，供 report.json 与 CI 汇总使用。"""
    stats = {feed.source: ReportFeedStats(feed.source, feed.category) for feed in feeds}
    for item in items:
        source_stats = stats.get(item["source"])
        if source_stats is not None:
            source_stats.add_item(item)
    for source, error in errors.items():
        if source in stats:
            stats[source].error = error
    return list(stats.values())


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

    feeds = select_feeds(args.feed)
    reset_image_dir()
    try:
        items, errors = collect(feeds)
    finally:
        browser.close()

    items.sort(key=dates.sort_key, reverse=True)
    items = items[:MAX_ITEMS]
    # 过滤订阅源属于本地调试，不做发布守门，否则永远抓不满下限。
    if not args.feed and len(items) < MIN_PUBLISH_ITEMS:
        LOGGER.error(
            "本轮只得到 %d 条，低于发布下限 %d，放弃写入快照", len(items), MIN_PUBLISH_ITEMS
        )
        return 1
    write_snapshot(items)
    write_report(REPORT_PATH, summarize(feeds, items, errors), len(items))
    LOGGER.info("写入 %d 条到 %s", len(items), Path(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
