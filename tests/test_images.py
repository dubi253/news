"""图片筛选与去重测试。"""

import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from newsfetch import images
from newsfetch.models import Candidate


def _png(width: int, height: int) -> bytes:
    """生成体积足够大的伪随机 PNG，避免被 MIN_IMAGE_BYTES 过滤掉。"""
    pixels = os.urandom(width * height * 3)
    image = Image.frombytes("RGB", (width, height), pixels)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class CandidateSelectionTests(unittest.TestCase):
    def test_srcset_picks_largest_variant(self):
        html = """
        <img src="/hero-400.jpg" srcset="/hero-400.jpg 400w, /hero-1600.jpg 1600w">
        <img class="author-avatar" src="/avatar.jpg">
        """
        selected = images.rank(images.collect_from_html(html, "https://example.com/news"))
        self.assertEqual([c.url for c in selected], ["https://example.com/hero-1600.jpg"])

    def test_same_image_at_two_sizes_is_deduped(self):
        html = """
        <img src="https://cdn.example.com/a/photo-640x360.jpg">
        <img src="https://cdn.example.com/a/photo-1600x900.jpg">
        """
        selected = images.rank(images.collect_from_html(html, "https://example.com"))
        self.assertEqual(len(selected), 1)
        self.assertIn("1600x900", selected[0].url)

    def test_rss_media_keeps_largest_variant(self):
        entry = {
            "media_content": [
                {"url": "/small.jpg", "width": "640", "height": "360"},
                {"url": "/large.jpg", "width": "1600", "height": "900"},
            ]
        }
        selected = images.rank(images.collect_from_rss(entry, "https://example.com/feed"))
        self.assertEqual([c.url for c in selected], ["https://example.com/large.jpg"])

    def test_avatar_and_logo_urls_are_rejected(self):
        self.assertTrue(images.is_non_article("https://example.com/logo.png"))
        self.assertTrue(images.is_non_article("https://example.com/u/avatar_120.png"))
        self.assertFalse(images.is_non_article("https://example.com/photos/2026/hero.jpg"))

    def test_wechat_image_is_upgraded_to_original(self):
        url = "https://mmbiz.qpic.cn/mmbiz_png/abc/640?wx_fmt=png"
        self.assertTrue(images.upgrade_url(url).endswith("/0?wx_fmt=png"))

    def test_normalisation_ignores_rendition_parameters(self):
        left = images.normalize_key("https://cdn.example.com/a.jpg?w=640&q=70")
        right = images.normalize_key("https://cdn.example.com/a.jpg?w=1600")
        self.assertEqual(left, right)

    def test_qiniu_processing_syntax_is_removed_without_reencoding(self):
        # 七牛把处理参数写成 imageMogr2/quality/90，重编码会变成 %2F 导致 400。
        url = "https://static.leiphone.com/a.jpg?imageMogr2/quality/90"
        self.assertEqual(images.upgrade_url(url), "https://static.leiphone.com/a.jpg")

    def test_signed_url_keeps_query_untouched(self):
        # Guardian 的 s= 是对 width/quality 一起签名，改动任一参数都会 401。
        url = (
            "https://i.guim.co.uk/img/media/abc/770_0_4580_3666/master/4580.jpg"
            "?width=700&quality=85&auto=format&fit=max&s=12e753f9ffe8618f09c67a8d5bf36aa5"
        )
        self.assertEqual(images.upgrade_url(url), url)

    def test_unknown_query_parameters_survive(self):
        url = "https://cdn.example.com/a.jpg?id=42&w=640"
        self.assertEqual(images.upgrade_url(url), "https://cdn.example.com/a.jpg?id=42")


class DownloadFilterTests(unittest.TestCase):
    def test_low_resolution_and_tiny_images_are_dropped(self):
        payloads = {
            "https://example.com/small.png": _png(200, 120),
            "https://example.com/icon.png": _png(44, 26),
            "https://example.com/hero.png": _png(1600, 900),
        }

        with TemporaryDirectory() as directory:
            dest = Path(directory) / "images"
            with patch.object(images, "_fetch_bytes", side_effect=lambda url: payloads.get(url)):
                accepted = images.download([Candidate(url) for url in payloads], dest, limit=5)

            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0].parent, dest)
            self.assertTrue(accepted[0].exists())

    def test_identical_bytes_are_only_stored_once(self):
        hero = _png(1600, 900)
        with TemporaryDirectory() as directory:
            dest = Path(directory) / "images"
            with patch.object(images, "_fetch_bytes", return_value=hero):
                accepted = images.download(
                    [
                        Candidate("https://example.com/a.png"),
                        Candidate("https://example.com/b.png"),
                    ],
                    dest,
                    limit=5,
                )
            self.assertEqual(len(accepted), 1)

    def test_limit_is_respected(self):
        heroes = {
            "https://example.com/1.png": _png(1600, 900),
            "https://example.com/2.png": _png(1600, 900),
            "https://example.com/3.png": _png(1600, 900),
        }
        with TemporaryDirectory() as directory:
            with patch.object(images, "_fetch_bytes", side_effect=lambda url: heroes[url]):
                accepted = images.download(
                    [Candidate(url) for url in heroes], Path(directory) / "images", limit=2
                )
            self.assertEqual(len(accepted), 2)

    def test_unreachable_image_is_skipped(self):
        with TemporaryDirectory() as directory:
            with patch.object(images, "_fetch_bytes", return_value=None):
                accepted = images.download(
                    [Candidate("https://example.com/dead.png")],
                    Path(directory) / "images",
                    limit=5,
                )
            self.assertEqual(accepted, [])


if __name__ == "__main__":
    unittest.main()
