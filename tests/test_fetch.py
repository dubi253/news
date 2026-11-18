import unittest
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

import fetch
from config import FEEDS, FeedConfig


class FetchTests(unittest.TestCase):
    def test_only_selected_leiphone_feeds_are_retained(self):
        urls = {feed.url for feed in FEEDS}
        sources = {feed.source for feed in FEEDS}

        self.assertEqual(
            {
                "雷峰网 - AI",
                "雷峰网 - 顶会专区",
                "雷峰网 - 芯片",
            },
            {source for source in sources if source.startswith("雷峰网")},
        )
        self.assertEqual(
            {
                "https://www.leiphone.com/feed/categoryRss/name/ai",
                "https://www.leiphone.com/feed/categoryRss/name/private",
                "https://www.leiphone.com/feed/categoryRss/name/chips",
            },
            {url for url in urls if "leiphone.com" in url},
        )

    def test_only_infoq_has_a_configured_default_timezone(self):
        configured = {
            feed.source: feed.default_timezone
            for feed in FEEDS
            if feed.default_timezone
        }

        self.assertEqual(configured, {"InfoQ 中文": "Asia/Shanghai"})

    def test_published_time_preserves_source_timezone(self):
        entry = {"published": "Mon, 16 Nov 2026 14:00:00 +0800"}

        self.assertEqual(fetch.published_time(entry), "2026-11-16T14:00:00+08:00")

    def test_published_time_uses_configured_timezone_for_naive_source(self):
        entry = {"published": "2026-11-16T14:00:00"}

        self.assertEqual(
            fetch.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_published_time_converts_aware_source_to_configured_timezone(self):
        entry = {"published": "2026-11-16T06:00:00+00:00"}

        self.assertEqual(
            fetch.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_published_time_does_not_assume_utc_for_naive_source(self):
        entry = {"published": "2026-11-16T14:00:00"}

        self.assertEqual(fetch.published_time(entry), "")

    def test_published_time_supports_rss_date_aliases(self):
        entry = {"date": "2026-11-16T14:00:00"}

        self.assertEqual(
            fetch.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_published_sort_key_compares_timezone_offsets_by_instant(self):
        later = {"published": "2026-11-16T06:00:00+00:00"}
        earlier = {"published": "2026-11-16T13:00:00+08:00"}

        self.assertGreater(
            fetch.published_sort_key(later),
            fetch.published_sort_key(earlier),
        )

    def test_unwrap_wechat_captcha_url(self):
        captcha_url = (
            "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha"
            "?poc_token=test&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Farticle"
        )

        self.assertEqual(
            fetch.unwrap_wechat_article_url(captcha_url),
            "https://mp.weixin.qq.com/s/article",
        )

    def test_parse_wechat_cookie_header(self):
        cookies = fetch.parse_wechat_cookie_header(
            "wxuin=123456; mm_lang=zh_CN"
        )

        self.assertEqual(cookies[0]["name"], "wxuin")
        self.assertEqual(cookies[0]["value"], "123456")
        self.assertEqual(cookies[0]["domain"], ".weixin.qq.com")

    def test_prepare_wechat_storage_state_from_json(self):
        state = json.dumps({"cookies": [], "origins": []})
        with patch.dict(os.environ, {"WECHAT_STORAGE_STATE": state}, clear=False):
            state_path, temporary_path = fetch.prepare_wechat_storage_state()

        try:
            self.assertTrue(state_path)
            self.assertTrue(Path(state_path).exists())
            self.assertEqual(temporary_path, state_path)
            Path(state_path).unlink()
        finally:
            if temporary_path and Path(temporary_path).exists():
                Path(temporary_path).unlink()

    def test_wechat_verification_page_is_detected(self):
        html = "<p>当前环境异常，完成验证后即可继续访问。</p><a>去验证</a>"

        self.assertTrue(
            fetch.is_wechat_verification_page(
                "https://mp.weixin.qq.com/s/article",
                html,
            )
        )

    def test_fetch_article_drops_wechat_verification_content(self):
        captcha_url = (
            "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha"
            "?poc_token=test&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Farticle"
        )

        with (
            patch(
                "fetch.parse_wechat_article",
                side_effect=fetch.WeChatVerifyError("verification required"),
            ),
            patch(
                "fetch.fetch_wechat_article_with_browser",
                return_value=("", [], "https://mp.weixin.qq.com/s/article"),
            ),
        ):
            content, images, resolved_link = fetch.fetch_article(captcha_url)

        self.assertEqual(content, "")
        self.assertEqual(images, [])
        self.assertEqual(resolved_link, "https://mp.weixin.qq.com/s/article")

    def test_fetch_article_uses_open_source_wechat_parser(self):
        result = Mock(
            is_valid=True,
            article_markdown="## 正文\n\n原文内容",
            images=["https://mmbiz.qpic.cn/test.jpg"],
        )
        link = "https://mp.weixin.qq.com/s/article"

        with patch("fetch.parse_wechat_article", return_value=result):
            content, images, resolved_link = fetch.fetch_article(link)

        self.assertEqual(content, "## 正文\n\n原文内容")
        self.assertEqual(images, ["https://mmbiz.qpic.cn/test.jpg"])
        self.assertEqual(resolved_link, link)

    def test_extract_wechat_article_html_prefers_js_content(self):
        html = (
            '<html><body><div id="js_content">'
            '<p>正文</p><img src="https://mmbiz.qpic.cn/mmbiz_jpg/test/640">'
            "</div><footer>公众号页脚</footer></body></html>"
        )

        article_html = fetch.extract_wechat_article_html(html)
        soup = __import__("bs4").BeautifulSoup(article_html, "lxml")

        self.assertEqual(soup.find("p").get_text(), "正文")
        self.assertIsNone(soup.find("footer"))

    def test_read_more_marker_triggers_full_article_fetch(self):
        content_html = (
            "<p>" + ("A long summary. " * 40) + '</p><a href="/article">Read more</a>'
        )
        self.assertTrue(fetch.has_read_more_marker(content_html))

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

    @patch("fetch.download_image", return_value="")
    @patch("fetch.fetch_article", return_value=("", [], "https://publisher.test/article"))
    @patch("fetch.GNews")
    def test_google_news_feed_uses_gnews_results(
        self, gnews_class, fetch_article, download_image
    ):
        gnews_class.return_value.get_news.return_value = [
            {
                "title": "Google result",
                "description": "Headline",
                "published date": "Mon, 16 Nov 2026 14:00:00 GMT",
                "url": "https://publisher.test/article",
            }
        ]

        items = fetch.fetch_feed(
            FeedConfig(
                "test",
                "Google",
                "https://news.google.com/rss/search?q=semiconductor+OR+foundry&hl=en-US&gl=US",
                1,
            )
        )

        gnews_class.assert_called_once_with(language="en-US", country="US", max_results=1)
        gnews_class.return_value.get_news.assert_called_once_with(
            "semiconductor OR foundry"
        )
        self.assertEqual(items[0]["link"], "https://publisher.test/article")
        self.assertEqual(items[0]["title"], "Google result")
        fetch_article.assert_called_once_with("https://publisher.test/article")

    @patch("fetch.download_image", return_value="")
    @patch(
        "fetch.fetch_article",
        return_value=("Full article content", [], "https://publisher.test/article"),
    )
    @patch("fetch.feedparser.parse")
    def test_read_more_entries_fetch_full_article(
        self, parse, fetch_article, download_image
    ):
        parse.return_value = Mock(
            entries=[
                {
                    "title": "Article",
                    "link": "https://publisher.test/article",
                    "description": (
                        "<p>" + ("Long summary. " * 40) + '</p><a href="/article">Read more</a>'
                    ),
                    "published": "Mon, 16 Nov 2026 14:00:00 +0000",
                }
            ],
            feed={"title": "Publisher"},
        )
        response = Mock()
        response.content = b"<rss />"
        response.raise_for_status.return_value = None

        with patch.object(fetch.SESSION, "get", return_value=response):
            items = fetch.fetch_feed(FeedConfig("test", "Test", "https://example.com/feed", 1))

        fetch_article.assert_called_once_with("https://publisher.test/article")
        self.assertEqual(items[0]["content"], "Full article content")


if __name__ == "__main__":
    unittest.main()
