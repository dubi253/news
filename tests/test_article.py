"""单篇文章抓取（正文 + 配图 + 发布时间）测试。"""

import unittest
from unittest.mock import Mock, patch

from newsfetch import article

BODY = "这是一段足够长的正文内容，用来验证正文不会被误判为导航碎片。" * 20


def _page(html: str, url: str = "https://example.com/a") -> Mock:
    return Mock(url=url, html=html, status=200, rendered=False, blocked=False)


def _fetch(html: str) -> article.Article:
    with (
        patch.object(article.http, "get_page", return_value=_page(html)),
        patch.object(article.browser, "render", return_value=None),
    ):
        return article.fetch("https://example.com/a")


class ArticleFetchTests(unittest.TestCase):
    def test_unreachable_page_returns_empty_article(self):
        with patch.object(article.http, "get_page", return_value=None):
            fetched = article.fetch("https://example.com/a")

        self.assertEqual(fetched.content, "")
        self.assertEqual(fetched.candidates, ())

    def test_navigation_only_body_is_discarded(self):
        html = "<html><body><article>- 首页<br>- 资讯<br>- 视频</article></body></html>"
        with (
            patch.object(article.http, "get_page", return_value=_page(html)),
            patch.object(article.browser, "render", return_value=None),
        ):
            fetched = article.fetch("https://example.com/a")

        self.assertEqual(fetched.content, "")

    def test_published_time_read_from_meta(self):
        # TechCrunch / Semiconductor Digest 等 WordPress 页面都声明 article:published_time。
        html = (
            '<html><head><meta property="article:published_time" '
            'content="2026-11-20T16:13:42-05:00"></head>'
            f"<body><article>{BODY}</article></body></html>"
        )
        self.assertEqual(_fetch(html).published, "2026-11-20T16:13:42-05:00")

    def test_published_time_falls_back_to_time_tag(self):
        html = (
            '<html><body><time datetime="2026-11-21T21:07:42+00:00">11月21日</time>'
            f"<article>{BODY}</article></body></html>"
        )
        self.assertEqual(_fetch(html).published, "2026-11-21T21:07:42+00:00")

    def test_published_time_empty_without_markers(self):
        html = f"<html><body><article>{BODY}</article></body></html>"
        self.assertEqual(_fetch(html).published, "")

    def test_published_time_tolerates_garbage_markers(self):
        # 站点把发布时间写成占位符时宁可为空，也不产出错误时间。
        html = (
            '<html><head><meta property="article:published_time" content="not-a-date"></head>'
            f"<body><article>{BODY}</article></body></html>"
        )
        self.assertEqual(_fetch(html).published, "")


if __name__ == "__main__":
    unittest.main()
