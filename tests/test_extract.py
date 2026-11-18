"""正文抽取与文本解码测试。"""

import unittest

from newsfetch import extract, text

LONG_PARAGRAPH = "这是一段足够长的正文内容，用来验证抽取结果不会被误判为导航碎片。" * 8


class ExtractTests(unittest.TestCase):
    def test_images_are_split_out_of_markdown(self):
        markdown = f"{LONG_PARAGRAPH}\n\n![图](https://example.com/a.jpg)\n\n{LONG_PARAGRAPH}"
        content, urls = extract.split_images(markdown)
        self.assertEqual(urls, ("https://example.com/a.jpg",))
        self.assertNotIn("![](", content)

    def test_read_more_marker_detected(self):
        html = f"<p>{LONG_PARAGRAPH}</p><a href='/x'>Read more</a>"
        self.assertTrue(extract.has_read_more_marker(html))
        self.assertFalse(extract.has_read_more_marker(f"<p>{LONG_PARAGRAPH}</p>"))

    def test_article_body_is_extracted(self):
        html = (
            "<html><body><nav>首页 资讯 视频</nav><article>"
            f"<h1>标题</h1><p>{LONG_PARAGRAPH}</p></article>"
            "<footer>版权</footer></body></html>"
        )
        extracted = extract.extract_html(html, "https://example.com/a")
        self.assertGreater(len(extracted.content), 200)
        self.assertNotIn("版权", extracted.content)

    def test_navigation_fragment_is_flagged(self):
        content = "- 首页\n- 资讯\n- 视频\n- 直播\n- 应用"
        self.assertTrue(extract.looks_like_navigation(content))
        self.assertFalse(extract.looks_like_navigation(LONG_PARAGRAPH))

    def test_login_wall_is_flagged(self):
        content = "扫描二维码登录\n\n打开微博手机 APP 扫码登录\n\n登录/注册"
        self.assertTrue(extract.looks_like_login_wall(content))
        self.assertFalse(extract.looks_like_login_wall(LONG_PARAGRAPH))


class TextTests(unittest.TestCase):
    def test_gbk_page_is_decoded_without_mojibake(self):
        raw = "中文正文内容".encode("gb18030")
        self.assertEqual(text.decode_body(raw, {"Content-Type": "text/html"}), "中文正文内容")

    def test_declared_charset_wins_when_correct(self):
        raw = "中文正文内容".encode()
        self.assertEqual(
            text.decode_body(raw, {"Content-Type": "text/html; charset=utf-8"}),
            "中文正文内容",
        )

    def test_mojibake_is_repaired(self):
        broken = "中文正文".encode().decode("latin-1")
        self.assertEqual(text.repair_mojibake(broken), "中文正文")

    def test_language_detection(self):
        self.assertEqual(text.detect_language({}, "中文标题"), "zh")
        self.assertEqual(text.detect_language({}, "English title"), "en")
        self.assertEqual(text.detect_language({"language": "en-US"}, "中文"), "en")


if __name__ == "__main__":
    unittest.main()
