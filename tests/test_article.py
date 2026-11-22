"""单篇文章抓取（正文 + 配图）测试。"""

import unittest
from unittest.mock import Mock, patch

from newsfetch import article

BODY = "这是一段足够长的正文内容，用来验证正文不会被误判为导航碎片。" * 20


def _page(html: str, url: str = "https://example.com/a") -> Mock:
    return Mock(url=url, html=html, status=200, rendered=False, blocked=False)


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


if __name__ == "__main__":
    unittest.main()
