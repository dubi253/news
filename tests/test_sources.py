"""订阅源流水线与微信、Google News 相关行为测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from config import MAX_IMAGES_PER_ITEM, MAX_IMAGES_PER_WECHAT_ITEM, FeedConfig
from newsfetch import feeds, googlenews, wechat
from newsfetch.models import Article, Candidate, NewsItem


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
            article_publish_time=1795231934,
        )
        with (
            patch.object(wechat, "parse_wechat_article", return_value=result),
            patch.object(wechat, "_with_browser") as browser_fetch,
        ):
            article = wechat.fetch("https://mp.weixin.qq.com/s/a")

        browser_fetch.assert_not_called()
        self.assertIn("内容", article.content)
        self.assertEqual([c.url for c in article.candidates], ["https://mmbiz.qpic.cn/a.png"])
        # 公众号镜像 RSS 没有 pubDate，发布时间只能来自文章页。
        self.assertEqual(article.published, "2026-11-21T11:32:14+08:00")

    def test_publish_time_is_read_from_page_script(self):
        html = "<script>var svrDate = \"1795334034\";\nvar oriCreateTime = '1795231934';\n</script>"
        self.assertEqual(wechat.publish_time(html), "2026-11-21T11:32:14+08:00")
        self.assertEqual(
            wechat.publish_time('<script>var ct = "1795231934";</script>'),
            "2026-11-21T11:32:14+08:00",
        )
        self.assertEqual(wechat.publish_time("<p>没有时间</p>"), "")
        self.assertEqual(wechat.publish_time(""), "")

    def test_browser_result_is_used_when_parser_hits_captcha(self):
        rendered_page = Mock(
            url="https://mp.weixin.qq.com/s/a",
            html=(
                "<script>var ct = '1795231934';</script>"
                '<div id="js_content"><p>' + "正文" * 200 + "</p></div>"
            ),
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
        self.assertEqual(article.published, "2026-11-21T11:32:14+08:00")


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


class ReuseTests(unittest.TestCase):
    """上一轮抓过的稿件直接复用，避免每轮重抓全文与图片。"""

    def _cached(
        self, title: str = "标题", images: tuple[str, ...] = ("data/images/a.jpg",)
    ) -> NewsItem:
        return {
            "category": "test",
            "source": "Test",
            "title": title,
            "language": "zh",
            "published": "2026-11-21T11:32:14+08:00",
            "link": "https://publisher.example/a",
            "content": "完整正文" * 200,
            "images": list(images),
        }

    def test_cached_item_is_reused_without_network(self):
        entry = {"title": "标题", "link": "https://publisher.example/a", "summary": "<p>摘要</p>"}
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        with TemporaryDirectory() as directory:
            image = Path(directory) / "data/images/a.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"stub")
            with (
                patch.object(feeds, "BASE_DIR", Path(directory)),
                patch.object(feeds.article_fetcher, "fetch") as article_fetch,
                patch.object(feeds.images, "download") as download,
            ):
                item = feeds.build_item(entry, feed, {entry["link"]: self._cached()})

        article_fetch.assert_not_called()
        download.assert_not_called()
        assert item is not None
        self.assertEqual(item["content"], "完整正文" * 200)
        self.assertEqual(item["images"], ["data/images/a.jpg"])

    def test_missing_local_image_forces_refetch(self):
        # 复用条目的图片必须还在本地，否则产物会指向不存在的文件。
        entry = {"title": "标题", "link": "https://publisher.example/a", "summary": "<p>摘要</p>"}
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        fetched = Article(content="新正文" * 200, candidates=(), url=entry["link"])
        with (
            patch.object(feeds, "BASE_DIR", Path("/nonexistent-root")),
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as article_fetch,
            patch.object(feeds.images, "download", return_value=[]),
        ):
            feeds.build_item(entry, feed, {entry["link"]: self._cached()})

        article_fetch.assert_called_once()

    def test_changed_title_forces_refetch(self):
        entry = {
            "title": "改过的标题",
            "link": "https://publisher.example/a",
            "summary": "<p>摘要</p>",
        }
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        fetched = Article(content="新正文" * 200, candidates=(), url=entry["link"])
        with (
            patch.object(feeds, "BASE_DIR", Path("/nonexistent-root")),
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as article_fetch,
            patch.object(feeds.images, "download", return_value=[]),
        ):
            feeds.build_item(entry, feed, {entry["link"]: self._cached()})

        article_fetch.assert_called_once()


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

        assert item is not None
        self.assertEqual(item["link"], "https://publisher.example/a")
        self.assertEqual(item["content"], "完整正文" * 100)
        self.assertEqual(item["images"], ["data/images/x.jpg"])
        self.assertEqual(item["published"], "2026-11-16T14:00:00+08:00")
        self.assertEqual(item["source"], "Test")
        # 产物字段必须与 NewsItem 契约一一对应，新增字段时同步改契约与本文档。
        self.assertEqual(set(item), set(NewsItem.__annotations__))

    def test_entry_without_usable_image_revisits_article(self):
        # 集微网 RSS 给的是够长的摘要 + 图标级 <img>：候选非空但没有正文大图，
        # 而且没有 pubDate。按“rank 后为空”判断才会回访，补回图和发布时间。
        entry = {
            "title": "标题",
            "link": "https://www.ijiwei.com/n/1",
            "summary": "<p>" + "摘要" * 300 + '</p><img class="icon" src="/icon.png">',
        }
        fetched = Article(
            content="完整正文" * 200,
            candidates=(Candidate("http://img.example/hero.png"),),
            url="https://www.ijiwei.com/n/1",
            published="2026-11-21T11:32:14+08:00",
        )
        feed = FeedConfig("semiconductor", "集微网", "https://example.com/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as article_fetch,
            patch.object(feeds.images, "download", return_value=[]),
        ):
            item = feeds.build_item(entry, feed)

        article_fetch.assert_called_once()
        assert item is not None
        self.assertEqual(item["content"], "完整正文" * 200)
        self.assertEqual(item["published"], "2026-11-21T11:32:14+08:00")

    def test_complete_entry_is_not_refetched(self):
        # 摘要够长、有大图、有时间：不必回访原文，否则每轮都要重抓一遍全站。
        entry = {
            "title": "标题",
            "link": "https://publisher.example/a",
            "summary": "<p>" + "正文" * 300 + '</p><img src="/hero.jpg">',
            "published": "Mon, 16 Nov 2026 14:00:00 +0800",
        }
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch") as article_fetch,
            patch.object(feeds.images, "download", return_value=[Path("/repo/data/images/x.jpg")]),
        ):
            feeds.build_item(entry, feed)

        article_fetch.assert_not_called()

    def test_entry_whose_images_all_fail_is_revisited(self):
        # 人民日报的 RSS 摘要里只有 go_top.png 这类站点素材：rank() 拦不住，
        # 下载后一张也不达标，必须回访原文补图。
        entry = {
            "title": "标题",
            "link": "https://publisher.example/a",
            "summary": "<p>" + "正文" * 300 + '</p><img src="/go_top.png">',
            "published": "Mon, 16 Nov 2026 14:00:00 +0800",
        }
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        fetched = Article(
            content="完整正文" * 200,
            candidates=(Candidate("https://publisher.example/hero.jpg"),),
            url=entry["link"],
        )
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as article_fetch,
            patch.object(
                feeds.images,
                "download",
                side_effect=[[], [Path("/repo/data/images/hero.jpg")]],
            ),
        ):
            item = feeds.build_item(entry, feed)

        article_fetch.assert_called_once()
        assert item is not None
        self.assertEqual(item["images"], ["data/images/hero.jpg"])

    def test_article_is_visited_only_once(self):
        # 已经回访过、仍然没有可用图片时不再重复抓同一篇。
        entry = {"title": "标题", "link": "https://publisher.example/a", "summary": "<p>摘要</p>"}
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        fetched = Article(content="正文" * 200, candidates=(), url=entry["link"])
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as article_fetch,
            patch.object(feeds.images, "download", return_value=[]),
        ):
            feeds.build_item(entry, feed)

        article_fetch.assert_called_once()

    def test_wechat_entry_takes_publish_time_from_article(self):
        # rssbox 的公众号镜像只有一个标题，没有 pubDate，只能回原文取时间。
        entry = {
            "title": "标题",
            "link": "https://mp.weixin.qq.com/s/a",
            "summary": "<p>" + "摘要" * 200 + '</p><img src="https://mmbiz.qpic.cn/a.png">',
        }
        fetched = Article(
            content="正文",
            candidates=(),
            url="https://mp.weixin.qq.com/s/a",
            published="2026-11-21T11:32:14+08:00",
        )
        feed = FeedConfig("test", "微信公众号-测试", "https://example.com/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched) as fetch,
            patch.object(feeds.images, "download", return_value=[]),
        ):
            item = feeds.build_item(entry, feed)

        assert item is not None
        fetch.assert_called_once()
        self.assertEqual(item["published"], "2026-11-21T11:32:14+08:00")

    def test_entry_publish_time_wins_over_article(self):
        entry = {
            "title": "标题",
            "link": "https://mp.weixin.qq.com/s/a",
            "summary": "<p>摘要</p>",
            "published": "Mon, 16 Nov 2026 14:00:00 +0800",
        }
        fetched = Article(
            content="正文" * 200,
            candidates=(),
            url="https://mp.weixin.qq.com/s/a",
            published="2026-11-21T11:32:14+08:00",
        )
        feed = FeedConfig("test", "微信公众号-测试", "https://example.com/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched),
            patch.object(feeds.images, "download", return_value=[]),
        ):
            item = feeds.build_item(entry, feed)

        assert item is not None
        self.assertEqual(item["published"], "2026-11-16T14:00:00+08:00")

    def test_wechat_article_allows_more_images(self):
        # 公众号正文配图密集，单独放宽上限，其余来源保持默认。
        entry = {"title": "标题", "link": "https://mp.weixin.qq.com/s/a", "summary": "<p>摘要</p>"}
        fetched = Article(
            content="正文" * 200,
            candidates=(Candidate("https://mmbiz.qpic.cn/a.png"),),
            url="https://mp.weixin.qq.com/s/a",
        )
        feed = FeedConfig("test", "微信公众号-测试", "https://example.com/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched),
            patch.object(feeds.images, "download", return_value=[]) as download,
        ):
            feeds.build_item(entry, feed)

        self.assertEqual(download.call_args.args[2], MAX_IMAGES_PER_WECHAT_ITEM)
        self.assertGreater(MAX_IMAGES_PER_WECHAT_ITEM, MAX_IMAGES_PER_ITEM)

    def test_other_sources_keep_default_image_limit(self):
        entry = {"title": "标题", "link": "https://publisher.example/a", "summary": "<p>摘要</p>"}
        fetched = Article(
            content="正文" * 200,
            candidates=(Candidate("https://publisher.example/hero.jpg"),),
            url="https://publisher.example/a",
        )
        feed = FeedConfig("test", "Test", "https://publisher.example/feed", 1)
        with (
            patch.object(feeds.article_fetcher, "fetch", return_value=fetched),
            patch.object(feeds.images, "download", return_value=[]) as download,
        ):
            feeds.build_item(entry, feed)

        self.assertEqual(download.call_args.args[2], MAX_IMAGES_PER_ITEM)

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
            patch.object(
                feeds, "build_item", side_effect=lambda entry, _feed, _previous=None: dict(entry)
            ),
        ):
            items = feeds.fetch_feed(feed)

        self.assertEqual(len(items), 2)

    def test_feed_is_requested_with_reader_identity(self):
        # 用浏览器 UA 抓 RSS 会被 Guardian 这类 WAF 判为伪装浏览器并 403。
        response = Mock(content=b"<rss />")
        feed = FeedConfig("test", "Test", "https://example.com/feed", 1)
        with (
            patch.object(feeds.http, "get_bytes", return_value=response) as get_bytes,
            patch.object(feeds.feedparser, "parse", return_value=Mock(entries=[])),
        ):
            feeds.fetch_feed(feed)

        self.assertEqual(get_bytes.call_args.kwargs["headers"], feeds.FEED_HEADERS)


if __name__ == "__main__":
    unittest.main()
