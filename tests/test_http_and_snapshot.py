"""HTTP 层与快照输出测试。"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import fetch
from config import FeedConfig
from newsfetch import http
from newsfetch.models import NewsItem


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
            self.assertEqual(len(fetch.collect(feeds)), 1)


if __name__ == "__main__":
    unittest.main()
