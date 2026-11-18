"""订阅源流水线与微信、Google News 相关行为测试。"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import FeedConfig
from newsfetch import feeds, googlenews, wechat
from newsfetch.models import Article, Candidate


class WeChatTests(unittest.TestCase):
    def test_captcha_url_is_unwrapped(self):
        captcha = (
            "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha"
            "?poc_token=t&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Farticle"
        )
        self.assertEqual(wechat.unwrap_captcha_url(captcha), "https://mp.weixin.qq.com/s/article")

    def test_verification_page_is_detected(self):
        self.assertTrue(
            wechat.is_verification_page(
                "https://mp.weixin.qq.com/s/a", "<p>当前环境异常，完成验证后即可继续访问。</p>"
            )
        )
        self.assertFalse(wechat.is_verification_page("https://mp.weixin.qq.com/s/a", "<p>正文</p>"))

    def test_cookie_header_is_parsed(self):
        cookies = wechat.parse_cookie_header("wxuin=123; mm_lang=zh_CN")
        self.assertEqual([c["name"] for c in cookies], ["wxuin", "mm_lang"])
        self.assertTrue(all(c["domain"] == ".weixin.qq.com" for c in cookies))

    def test_article_container_is_isolated(self):
        html = (
            '<html><body><div id="js_content"><p>正文</p></div><footer>页脚</footer></body></html>'
        )
        self.assertIn("正文", wechat.article_html(html))
        self.assertNotIn("页脚", wechat.article_html(html))

    def test_parser_result_is_used_when_complete(self):
        result = Mock(
            is_valid=True,
            article_markdown="# 标题\n\n" + "内容" * 200,
            images=["https://mmbiz.qpic.cn/a.png"],
        )
        with (
            patch.object(wechat, "parse_wechat_article", return_value=result),
            patch.object(wechat, "_with_browser") as browser_fetch,
        ):
            article = wechat.fetch("https://mp.weixin.qq.com/s/a")

        browser_fetch.assert_not_called()
        self.assertIn("内容", article.content)
        self.assertEqual([c.url for c in article.candidates], ["https://mmbiz.qpic.cn/a.png"])

    def test_browser_result_is_used_when_parser_hits_captcha(self):
        rendered_page = Mock(
            url="https://mp.weixin.qq.com/s/a",
            html='<div id="js_content"><p>' + "正文" * 200 + "</p></div>",
            images=[],
        )
        with (
            patch.object(
                wechat, "parse_wechat_article", side_effect=wechat.WeChatVerifyError("captcha")
            ),
            patch.object(wechat.browser, "render_persistent", return_value=rendered_page),
            patch.object(wechat, "WECHAT_PROFILE_DIR", "/tmp/wechat-test-profile"),
        ):
            article = wechat.fetch("https://mp.weixin.qq.com/s/a")

        self.assertGreater(len(article.content), 200)


class GoogleNewsTests(unittest.TestCase):
    def test_feed_detection(self):
        self.assertTrue(googlenews.is_google_news_feed("https://news.google.com/rss/search?q=tsmc"))
        self.assertFalse(googlenews.is_google_news_feed("https://example.com/rss"))

    def test_decoded_link_is_preferred(self):
        with patch.object(
            googlenews,
            "_decode",
            return_value="https://publisher.example/article",
        ):
            resolved = googlenews.resolve_url("https://news.google.com/rss/articles/CBMiX")
        self.assertEqual(resolved, "https://publisher.example/article")

    def test_failed_resolution_keeps_original_link(self):
        with (
            patch.object(googlenews, "_decode", return_value=""),
            patch.object(googlenews, "_navigate", return_value=""),
        ):
            link = "https://news.google.com/rss/articles/CBMiX"
            self.assertEqual(googlenews.resolve_url(link), link)


class FeedPipelineTests(unittest.TestCase):
    def test_item_keeps_entry_link_and_uses_article_body(self):
        entry = {
            "title": "标题",
            "link": "https://publisher.example/a",
            "summary": "<p>摘要</p>",
            "published": "Mon, 16 Nov 2026 14:00:00 +0800",
        }
        fetched = Article(
            content="完整正文" * 100,
            candidates=(Candidate("https://publisher.example/hero.jpg"),),
            url="https://publisher.example/a?utm=x",
        )
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched),
            patch.object(
                feeds.images,
                "download",
                return_value=[Path("/repo/data/images/x.jpg")],
            ),
        ):
            item = feeds.build_item(entry, feed)

        self.assertEqual(item["link"], "https://publisher.example/a")
        self.assertEqual(item["content"], "完整正文" * 100)
        self.assertEqual(item["images"], ["data/images/x.jpg"])
        self.assertEqual(item["published"], "2026-11-16T14:00:00+08:00")
        self.assertEqual(item["source"], "Test")

    def test_entry_without_title_or_link_is_skipped(self):
        feed = FeedConfig("test", "Test", "https://example.com/feed", 1)
        self.assertIsNone(feeds.build_item({"title": "", "link": "https://x.test/a"}, feed))
        self.assertIsNone(feeds.build_item({"title": "标题", "link": ""}, feed))

    def test_feed_limit_is_applied(self):
        parsed = Mock(entries=[{"title": f"t{i}", "link": f"https://x.test/{i}"} for i in range(5)])
        response = Mock(content=b"<rss />")
        feed = FeedConfig("test", "Test", "https://example.com/feed", 2)
        with (
            patch.object(feeds.http, "get_bytes", return_value=response),
            patch.object(feeds.feedparser, "parse", return_value=parsed),
            patch.object(feeds, "build_item", side_effect=lambda entry, _: dict(entry)),
        ):
            items = feeds.fetch_feed(feed)

        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
