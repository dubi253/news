"""抓取统计（report.json）测试。"""

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import fetch
from config import FeedConfig
from newsfetch import report
from newsfetch.models import NewsItem


def _item(
    source: str,
    *,
    content: str = "正文",
    images: tuple[str, ...] = ("data/images/a.jpg",),
    published: str = "2026-11-22T10:00:00+08:00",
) -> NewsItem:
    return {
        "category": "test",
        "source": source,
        "title": "标题",
        "language": "zh",
        "published": published,
        "link": f"https://a.test/{source}",
        "content": content,
        "images": list(images),
    }


class SummarizeTests(unittest.TestCase):
    def test_counts_quality_gaps_per_source(self):
        feeds = (
            FeedConfig("a", "A", "https://a.test/feed"),
            FeedConfig("a", "B", "https://b.test"),
        )
        items = [
            _item("A"),
            _item("A", content="  ", images=()),
            _item("B", published=""),
        ]
        stats = {entry.source: entry for entry in fetch.summarize(feeds, items, {})}

        self.assertEqual(stats["A"].items, 2)
        self.assertEqual(stats["A"].empty_content, 1)
        self.assertEqual(stats["A"].no_images, 1)
        self.assertEqual(stats["B"].no_published, 1)
        self.assertEqual(stats["B"].no_images, 0)

    def test_feed_errors_are_attached(self):
        feeds = (FeedConfig("a", "A", "https://a.test/feed"),)
        stats = fetch.summarize(feeds, [], {"A": "RuntimeError: boom"})
        self.assertEqual(stats[0].error, "RuntimeError: boom")
        self.assertEqual(stats[0].items, 0)


class ReportTests(unittest.TestCase):
    def _stats(self):
        feeds = (FeedConfig("a", "A", "https://a.test/feed"),)
        items = [_item("A"), _item("A", images=(), published="")]
        return fetch.summarize(feeds, items, {"A": ""})

    def test_write_report_is_readable_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report.write_report(path, self._stats(), count=2)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["count"], 2)
        self.assertEqual(set(payload), {"updated", "count", "reused", "feeds"})
        self.assertEqual(payload["feeds"][0]["source"], "A")
        self.assertEqual(payload["feeds"][0]["no_images"], 1)

    def test_markdown_summary_lists_problem_feeds(self):
        markdown = report.to_markdown(report.build_payload(self._stats(), 2))
        self.assertIn("| A | a | 2 | 0 | 1 | 1 |", markdown)
        # 0 条的源会被单独点名，方便一眼看出当天哪个源挂了。
        markdown = report.to_markdown(
            report.build_payload(
                [report.FeedStats("B", "b", items=0, error="RuntimeError: boom")], 0
            )
        )
        self.assertIn("需要关注的订阅源：B", markdown)

    def test_cli_prints_markdown(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report.write_report(path, self._stats(), count=2)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(report.main([str(path)]), 0)
        self.assertIn("| 来源 |", buffer.getvalue())
        self.assertEqual(report.main([]), 2)


if __name__ == "__main__":
    unittest.main()
