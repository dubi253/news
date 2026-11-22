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
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from config import (
    DATA_DIR,
    FALLBACK_MAX_AGE_HOURS,
    FEED_WORKERS,
    FEEDS,
    IMAGE_DIR,
    MAX_ITEMS,
    MIN_PUBLISH_ITEMS,
    OUTPUT_PATH,
    PREVIOUS_PATH,
    REPORT_PATH,
    FeedConfig,
)
from newsfetch import browser, dates, dedupe
from newsfetch.feeds import fetch_feed, is_complete
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


def prepare_image_dir() -> None:
    """准备图片目录。

    上一轮的图片保留在原处（文件名由内容哈希决定，复用的条目直接引用它们），
    本轮结束后由 ``prune_images`` 删掉产物不再引用的文件，目录仍然与快照一致。
    """
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def prune_images(items: Sequence[NewsItem]) -> int:
    """删除产物未引用的图片，返回删除数量。"""
    referenced = {Path(path).name for item in items for path in item["images"]}
    removed = 0
    for path in IMAGE_DIR.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
            removed += 1
    return removed


def load_previous(path: Path) -> dict[str, NewsItem]:
    """读取上一轮快照，返回 link → 条目索引；文件缺失或损坏时返回空索引。"""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("items") or []
    except (OSError, ValueError) as exc:
        LOGGER.warning("无法读取上一轮快照 %s: %s", path, exc)
        return {}
    return {str(item["link"]): item for item in entries if item.get("link")}


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


def _fallback_items(feed: FeedConfig, previous: Mapping[str, NewsItem]) -> list[NewsItem]:
    """整源抓取失败时沿用它上一轮的条目，避免一次短暂故障让整个源从产物里消失。

    只沿用完整（正文够长、配图仍在本地）且发布时间在 ``FALLBACK_MAX_AGE_HOURS``
    以内的条目，源持续失效时旧条目会自己过期；没有发布时间的条目无法判断新旧
    （集微网这类源本来就不给时间），一并沿用。
    """
    deadline = time.time() - FALLBACK_MAX_AGE_HOURS * 3600
    fallback: list[NewsItem] = []
    for item in previous.values():
        if item.get("source") != feed.source or not is_complete(item):
            continue
        published = dates.sort_key(item)
        if published and published < deadline:
            continue
        fallback.append(item)
    return fallback


def _fetch_one(feed: FeedConfig, previous: Mapping[str, NewsItem]) -> tuple[list[NewsItem], str]:
    """抓取单个订阅源；异常只记在本源上，不中断整轮抓取。

    失败的源沿用上一轮该源的条目并照常在 report 里记下异常：源挂掉要看得到，
    但它上一轮已经抓到的好数据不该跟着一起丢。
    """
    try:
        return fetch_feed(feed, previous), ""
    except Exception as exc:
        # 订阅源互相独立：单个源的任何失败都不应中断整轮抓取，
        # LOGGER.exception 记录完整堆栈便于事后定位。
        LOGGER.exception("订阅源抓取异常: %s", feed.source)
        return _fallback_items(feed, previous), f"{type(exc).__name__}: {exc}"


def collect(
    feeds: Sequence[FeedConfig],
    previous: Mapping[str, NewsItem] | None = None,
    workers: int = FEED_WORKERS,
) -> tuple[list[NewsItem], dict[str, str]]:
    """并发抓取全部订阅源，按链接去重后返回。

    订阅源之间没有共享状态，瓶颈是网络等待，因此按源并发；线程内复用各自的
    HTTP 会话与浏览器实例。``pool.map`` 保序，结果与串行抓取一致。

    Args:
        feeds: 要抓取的订阅源。
        previous: 上一轮快照索引，命中时该条目直接复用。
        workers: 并发线程数，1 表示串行。

    Returns:
        去重后的条目，以及抓取失败的订阅源到异常简述的映射。
    """
    cached = previous or {}
    if workers > 1 and len(feeds) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda feed: _fetch_one(feed, cached), feeds))
    else:
        results = [_fetch_one(feed, cached) for feed in feeds]

    items: list[NewsItem] = []
    seen: set[str] = set()
    errors: dict[str, str] = {}
    for feed, (feed_items, error) in zip(feeds, results, strict=True):
        if error:
            errors[feed.source] = error
        for item in feed_items:
            link = str(item["link"])
            if link in seen:
                continue
            seen.add(link)
            items.append(item)
    items, merged = dedupe.dedupe(items)
    if merged:
        LOGGER.info("合并 %d 条跨源重复稿件", merged)
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


def select_items(items: Sequence[NewsItem], limit: int) -> list[NewsItem]:
    """按分类配额挑选条目，再按时间倒序返回。

    单纯按时间截断时，半导体这类源多、更新快的分类会把冷门分类整轮挤出产物；
    先按 ``limit / 分类数`` 给每个分类保底名额，富余名额再按时间补满。

    Args:
        items: 已按时间倒序排好的候选条目。
        limit: 产物总条数上限。

    Returns:
        选中的条目，仍按时间倒序。
    """
    groups: dict[str, list[NewsItem]] = {}
    for item in items:
        groups.setdefault(item["category"], []).append(item)
    if not groups:
        return []
    quota = max(1, limit // len(groups))
    chosen: dict[str, NewsItem] = {}
    for group in groups.values():
        for item in group[:quota]:
            chosen[item["link"]] = item
    if len(chosen) < limit:
        for item in items:
            if len(chosen) >= limit:
                break
            chosen.setdefault(item["link"], item)
    selected = list(chosen.values())
    selected.sort(key=dates.sort_key, reverse=True)
    return selected[:limit]


def previous_path() -> Path:
    """上一轮快照的位置，允许用 NEWS_PREVIOUS_JSON 指向 CI 还原出来的副本。"""
    return Path(os.environ.get("NEWS_PREVIOUS_JSON", "") or PREVIOUS_PATH)


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
    parser.add_argument(
        "--workers",
        type=int,
        default=FEED_WORKERS,
        metavar="N",
        help="订阅源并发数，1 表示串行（默认 %(default)s）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    feeds = select_feeds(args.feed)
    previous = load_previous(previous_path())
    prepare_image_dir()
    try:
        items, errors = collect(feeds, previous, workers=max(1, args.workers))
    finally:
        browser.close()

    items.sort(key=dates.sort_key, reverse=True)
    items = select_items(items, MAX_ITEMS)
    # 过滤订阅源属于本地调试，不做发布守门，否则永远抓不满下限。
    if not args.feed and len(items) < MIN_PUBLISH_ITEMS:
        LOGGER.error(
            "本轮只得到 %d 条，低于发布下限 %d，放弃写入快照", len(items), MIN_PUBLISH_ITEMS
        )
        return 1
    write_snapshot(items)
    removed = prune_images(items)
    reused = sum(
        1
        for item in items
        if previous.get(item["link"], {}).get("content") == item.get("content")
        and item.get("content")
    )
    write_report(REPORT_PATH, summarize(feeds, items, errors), len(items), reused=reused)
    LOGGER.info(
        "写入 %d 条到 %s（复用 %d 条，清理 %d 张旧图）",
        len(items),
        Path(OUTPUT_PATH),
        reused,
        removed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
