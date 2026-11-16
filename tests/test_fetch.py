import unittest
from unittest.mock import Mock, patch

import fetch
from config import FeedConfig


class FetchTests(unittest.TestCase):
    def test_published_time_preserves_source_timezone_as_utc(self):
        entry = {"published": "Mon, 16 Nov 2026 14:00:00 +0800"}

        self.assertEqual(fetch.published_time(entry), "2026-11-16T06:00:00+00:00")

    def test_published_time_uses_configured_timezone_for_naive_source(self):
        entry = {"published": "2026-11-16T14:00:00"}

        self.assertEqual(
            fetch.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T06:00:00+00:00",
        )

    def test_published_time_does_not_assume_utc_for_naive_source(self):
        entry = {"published": "2026-11-16T14:00:00"}

        self.assertEqual(fetch.published_time(entry), "")

    def test_html_images_selects_largest_srcset_and_skips_avatar(self):
        value = """
        <img src="/hero-400.jpg" srcset="/hero-400.jpg 400w, /hero-1200.jpg 1200w">
        <img class="author-avatar" src="/avatar-1200.jpg">
        """

        self.assertEqual(
            fetch.html_images(value, "https://example.com/news"),
            ["https://example.com/hero-1200.jpg"],
        )

    def test_rss_images_selects_largest_media_variant(self):
        entry = {
            "media_content": [
                {"url": "/hero-small.jpg", "width": "640", "height": "360"},
                {"url": "/hero-large.jpg", "width": "1600", "height": "900"},
            ]
        }

        self.assertEqual(
            fetch.rss_images(entry, "https://example.com/feed"),
            ["https://example.com/hero-large.jpg"],
        )

    @patch("fetch.download_image", return_value="data/images/article.jpg")
    @patch("fetch.fetch_article", return_value=("Full article content", ["https://publisher.test/hero.jpg"], "https://publisher.test/article"))
    @patch("fetch.feedparser.parse")
    def test_google_news_entries_fetch_publisher_article(
        self, parse, fetch_article, download_image
    ):
        parse.return_value = Mock(
            entries=[
                {
                    "title": "Google result",
                    "link": "https://news.google.com/rss/articles/example",
                    "description": "Headline only",
                    "published": "Mon, 16 Nov 2026 14:00:00 +0000",
                }
            ],
            feed={"title": "Google News"},
        )
        response = Mock()
        response.content = b"<rss />"
        response.raise_for_status.return_value = None

        with patch.object(fetch.SESSION, "get", return_value=response):
            items = fetch.fetch_feed(FeedConfig("test", "Test", "https://example.com/feed", 1))

        fetch_article.assert_called_once_with("https://news.google.com/rss/articles/example")
        self.assertEqual(items[0]["link"], "https://publisher.test/article")
        self.assertEqual(items[0]["content"], "Full article content")
        download_image.assert_called_once_with("https://publisher.test/hero.jpg", 0)


if __name__ == "__main__":
    unittest.main()
