"""每轮抓取的分源统计。

``data/news.json`` 是产物契约，``data/report.json`` 是诊断附件：这一轮哪个源没
抓到、多少条缺正文/缺图/缺时间，都写在这里。CI 会用 ``python -m newsfetch.report``
把它渲染成 job summary，排障时不必再翻整轮日志。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from newsfetch.models import NewsItem


@dataclass(slots=True)
class FeedStats:
    """单个订阅源在一轮抓取中的统计。

    Attributes:
        source: 来源名，与 ``FeedConfig.source`` 一致。
        category: 分类。
        items: 进入产物的条目数。
        empty_content: 正文为空的条目数。
        no_images: 没有任何配图的条目数。
        no_published: 没有发布时间的条目数。
        error: 整源抓取失败时的异常简述，正常为空串。
    """

    source: str
    category: str
    items: int = 0
    empty_content: int = 0
    no_images: int = 0
    no_published: int = 0
    error: str = ""

    def add_item(self, item: NewsItem) -> None:
        """累计一条产物条目的质量缺陷。"""
        self.items += 1
        if not item["content"].strip():
            self.empty_content += 1
        if not item["images"]:
            self.no_images += 1
        if not item["published"]:
            self.no_published += 1


def build_payload(stats: Sequence[FeedStats], count: int, reused: int = 0) -> dict[str, Any]:
    """组装 report.json 的内容。"""
    return {
        "updated": datetime.now(UTC).isoformat(),
        "count": count,
        "reused": reused,
        "feeds": [asdict(entry) for entry in stats],
    }


def write_report(path: Path, stats: Sequence[FeedStats], count: int, reused: int = 0) -> None:
    """原子地写入 report.json。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="report-", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(build_payload(stats, count, reused), handle, ensure_ascii=False, indent=2)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def to_markdown(payload: dict[str, Any]) -> str:
    """把统计渲染成 Markdown 表格（供 GitHub Actions job summary）。"""
    feeds = payload.get("feeds") or []
    header = f"共 {payload.get('count', 0)} 条，覆盖 {len(feeds)} 个订阅源"
    if payload.get("reused"):
        header += f"，其中 {payload['reused']} 条复用上一轮"
    lines = [
        header,
        "",
        "| 来源 | 分类 | 条目 | 空正文 | 无图 | 无时间 | 异常 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        "| {source} | {category} | {items} | {empty_content} | {no_images} "
        "| {no_published} | {error} |".format(
            source=feed.get("source", ""),
            category=feed.get("category", ""),
            items=feed.get("items", 0),
            empty_content=feed.get("empty_content", 0),
            no_images=feed.get("no_images", 0),
            no_published=feed.get("no_published", 0),
            error=feed.get("error", "") or "",
        )
        for feed in feeds
    )
    broken = [feed for feed in feeds if feed.get("error") or feed.get("items") == 0]
    if broken:
        lines += ["", f"需要关注的订阅源：{', '.join(feed.get('source', '') for feed in broken)}"]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """把 report.json 渲染成 Markdown 输出到标准输出。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("用法: python -m newsfetch.report data/report.json", file=sys.stderr)
        return 2
    payload = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    print(to_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
