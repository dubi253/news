"""HTTP 层与快照输出测试。"""

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import fetch
from config import FeedConfig
from newsfetch import http
from newsfetch.models import NewsItem


def _entry(feed: FeedConfig) -> NewsItem:
    """一条满足 NewsItem 契约的最小条目，供并发/去重相关测试复用。"""
    return {
        "category": "a",
        "source": feed.source,
        "title": f"标题-{feed.source}",
        "language": "zh",
        "published": "",
        "link": f"https://a.test/{feed.source}",
        "content": "正文",
        "images": [],
    }


class BlockDetectionTests(unittest.TestCase):
    def test_blocked_status_codes(self):
        self.assertTrue(http.looks_blocked(403, ""))
        self.assertTrue(http.looks_blocked(429, ""))
        self.assertFalse(http.looks_blocked(200, "<html>正文</html>"))

    def test_verification_markers(self):
        self.assertTrue(http.looks_blocked(200, "<title>Just a moment...</title>"))
        self.assertTrue(http.looks_blocked(200, "<div>请完成安全验证</div>"))
        self.assertFalse(http.looks_blocked(200, "<article>正常正文</article>"))

    def test_browser_is_escalated_for_blocked_page(self):
        blocked = Mock(
            status_code=403,
            ok=False,
            text="",
            content=b"<html>denied</html>",
            url="https://example.com/a",
        )
        blocked.headers = {"Content-Type": "text/html"}
        rendered = Mock(
            url="https://example.com/a",
            html="<article><p>" + "正文" * 300 + "</p></article>",
            status=200,
            rendered=True,
            blocked=False,
        )
        with (
            patch.object(http._SESSION, "get", return_value=blocked),
            patch.object(http.browser, "render", return_value=rendered),
        ):
            page = http.get_page("https://example.com/a")

        self.assertTrue(page.rendered)
        self.assertIn("正文", page.html)


class SnapshotTests(unittest.TestCase):
    def test_item_contract_is_documented_fields(self):
        # data/news.json 的字段只增不改；改名必须同时更新 AGENTS.md 与迁移说明。
        self.assertEqual(
            set(NewsItem.__annotations__),
            {"category", "source", "title", "language", "published", "link", "content", "images"},
        )

    def test_snapshot_contract(self):
        items = [
            {"category": "technology", "link": "https://a.test/1"},
            {"category": "ai", "link": "https://a.test/2"},
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory) / "news.json"
            with (
                patch.object(fetch, "DATA_DIR", Path(directory)),
                patch.object(fetch, "OUTPUT_PATH", output),
            ):
                fetch.write_snapshot(items)

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(set(payload), {"updated", "count", "categories", "items"})
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["categories"], ["ai", "technology"])

    def test_feed_selection_by_keyword(self):
        feeds = (
            FeedConfig("a", "InfoQ 中文", "https://www.infoq.cn/feed.xml"),
            FeedConfig("b", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        )
        with patch.object(fetch, "FEEDS", feeds):
            self.assertEqual([f.source for f in fetch.select_feeds(["InfoQ"])], ["InfoQ 中文"])
            self.assertEqual(len(fetch.select_feeds([])), 2)

    def test_collect_dedupes_by_link(self):
        feeds = (FeedConfig("a", "A", "https://a.test/feed"),)
        duplicate = {"link": "https://a.test/1", "category": "a", "source": "A"}
        with patch.object(fetch, "fetch_feed", return_value=[duplicate, dict(duplicate)]):
            items, errors = fetch.collect(feeds)
        self.assertEqual(len(items), 1)
        self.assertEqual(errors, {})

    def test_collect_records_feed_errors(self):
        feeds = (FeedConfig("a", "A", "https://a.test/feed"),)
        with patch.object(fetch, "fetch_feed", side_effect=RuntimeError("boom")):
            items, errors = fetch.collect(feeds)
        self.assertEqual(items, [])
        self.assertEqual(errors, {"A": "RuntimeError: boom"})

    def test_feeds_are_fetched_concurrently(self):
        # 两个源必须同时进入抓取，否则 barrier 超时（串行时第二个永远等不到）。
        barrier = threading.Barrier(2, timeout=5)

        def fake_fetch(feed):
            barrier.wait()
            return [_entry(feed)]

        feeds = (
            FeedConfig("a", "A", "https://a.test/1"),
            FeedConfig("a", "B", "https://a.test/2"),
        )
        with patch.object(fetch, "fetch_feed", side_effect=fake_fetch):
            items, errors = fetch.collect(feeds, workers=2)

        self.assertEqual(errors, {})
        self.assertEqual([item["source"] for item in items], ["A", "B"])

    def test_concurrent_collect_keeps_feed_order(self):
        def fake_fetch(feed):
            time.sleep(0.01 if feed.source == "A" else 0.03)
            return [_entry(feed)]

        feeds = (
            FeedConfig("a", "A", "https://a.test/1"),
            FeedConfig("a", "B", "https://a.test/2"),
        )
        with patch.object(fetch, "fetch_feed", side_effect=fake_fetch):
            items, _ = fetch.collect(feeds, workers=2)

        self.assertEqual([item["source"] for item in items], ["A", "B"])


class QuotaSelectionTests(unittest.TestCase):
    """条目多的大分类不能把冷门分类整轮挤出产物。"""

    @staticmethod
    def _item(category: str, index: int, published: str) -> NewsItem:
        return {
            "category": category,
            "source": category,
            "title": f"{category}-{index}",
            "link": f"https://a.test/{category}/{index}",
            "published": published,
            "content": "正文",
            "images": [],
            "language": "zh",
        }

    def test_every_category_keeps_a_quota(self):
        items = [
            self._item("semiconductor", index, f"2026-11-22T{index:02d}:00:00+08:00")
            for index in range(10)
        ]
        items += [
            self._item("shanghai", index, f"2026-11-21T{index:02d}:00:00+08:00")
            for index in range(10)
        ]
        selected = fetch.select_items(items, limit=4)
        self.assertEqual(len(selected), 4)
        self.assertEqual({item["category"] for item in selected}, {"semiconductor", "shanghai"})

    def test_leftover_slots_are_filled_by_time(self):
        items = [
            self._item("semiconductor", index, "2026-11-22T10:00:00+08:00") for index in range(3)
        ]
        items.append(self._item("shanghai", 0, "2026-11-20T10:00:00+08:00"))
        selected = fetch.select_items(items, limit=3)
        self.assertEqual(len(selected), 3)
        self.assertEqual(sum(1 for item in selected if item["category"] == "semiconductor"), 2)
        self.assertEqual(sum(1 for item in selected if item["category"] == "shanghai"), 1)

    def test_selection_stays_in_time_order(self):
        items = [
            self._item("a", 0, "2026-11-20T10:00:00+08:00"),
            self._item("b", 0, "2026-11-22T10:00:00+08:00"),
            self._item("a", 1, "2026-11-21T10:00:00+08:00"),
        ]
        selected = fetch.select_items(items, limit=3)
        self.assertEqual(
            [item["published"][:10] for item in selected],
            ["2026-11-22", "2026-11-21", "2026-11-20"],
        )

    def test_empty_input(self):
        self.assertEqual(fetch.select_items([], limit=10), [])


class PublishGuardTests(unittest.TestCase):
    """坏掉的一轮必须失败退出，不能把线上快照覆盖成残缺数据。"""

    def _run(self, items, argv):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "news.json"
            with (
                patch.object(fetch, "collect", return_value=(items, {})),
                patch.object(fetch, "select_feeds", return_value=()),
                patch.object(fetch, "reset_image_dir"),
                patch.object(fetch.browser, "close"),
                patch.object(fetch, "DATA_DIR", Path(directory)),
                patch.object(fetch, "OUTPUT_PATH", output),
                patch.object(fetch, "REPORT_PATH", Path(directory) / "report.json"),
            ):
                code = fetch.main(argv)
            written = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
        return code, written

    @staticmethod
    def _items(count):
        return [
            {"category": "technology", "source": "A", "link": f"https://a.test/{index}"}
            for index in range(count)
        ]

    def test_full_run_below_minimum_refuses_to_write(self):
        code, written = self._run(self._items(fetch.MIN_PUBLISH_ITEMS - 1), [])
        self.assertEqual(code, 1)
        self.assertIsNone(written)

    def test_full_run_above_minimum_writes_snapshot(self):
        code, written = self._run(self._items(fetch.MIN_PUBLISH_ITEMS), [])
        self.assertEqual(code, 0)
        assert written is not None
        self.assertEqual(written["count"], fetch.MIN_PUBLISH_ITEMS)

    def test_filtered_run_skips_guard(self):
        # --feed 是本地调试入口，抓到几条就写几条，不受发布下限约束。
        code, written = self._run(self._items(1), ["--feed", "InfoQ"])
        self.assertEqual(code, 0)
        assert written is not None
        self.assertEqual(written["count"], 1)


if __name__ == "__main__":
    unittest.main()
