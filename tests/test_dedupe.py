"""跨源重复稿件去重测试。"""

import unittest

from newsfetch import dedupe
from newsfetch.models import NewsItem


def _item(
    title: str,
    *,
    link: str,
    source: str = "源",
    content: str = "正文" * 50,
    images: tuple[str, ...] = (),
    published: str = "",
) -> NewsItem:
    return {
        "category": "china",
        "source": source,
        "title": title,
        "language": "zh",
        "published": published,
        "link": link,
        "content": content,
        "images": list(images),
    }


class NormalizeTitleTests(unittest.TestCase):
    def test_google_news_publisher_suffix_is_stripped(self):
        self.assertEqual(
            dedupe.normalize_title("行贿犯罪嫌疑人刘贤志被遣返回国 - 新华社"),
            dedupe.normalize_title("行贿犯罪嫌疑人刘贤志被遣返回国"),
        )

    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(dedupe.normalize_title("TSMC's Q3 Earnings!"), "tsmcsq3earnings")

    def test_edition_prefix_is_not_stripped_as_publisher(self):
        # “01版 - 李强同新加坡总理黄循财会谈”是版次+标题，不能退化成“01版”。
        self.assertEqual(
            dedupe.normalize_title("01版 - 李强同新加坡总理黄循财会谈"),
            "01版李强同新加坡总理黄循财会谈",
        )


class DedupeTests(unittest.TestCase):
    def test_same_story_from_two_sources_is_merged(self):
        items = [
            _item("行贿犯罪嫌疑人刘贤志被遣返回国", link="https://a.test/1", source="澎湃新闻"),
            _item("行贿犯罪嫌疑人刘贤志被遣返回国", link="https://b.test/2", source="新华社"),
        ]
        kept, dropped = dedupe.dedupe(items)
        self.assertEqual(dropped, 1)
        self.assertEqual([item["source"] for item in kept], ["澎湃新闻"])

    def test_richer_item_wins_and_keeps_first_position(self):
        items = [
            _item("三星内存产能已预订一空", link="https://a.test/1", content="短"),
            _item("没关系的另一条", link="https://c.test/3"),
            _item(
                "三星内存产能已预订一空",
                link="https://b.test/2",
                content="完整正文" * 100,
                images=("data/images/x.jpg",),
            ),
        ]
        kept, dropped = dedupe.dedupe(items)
        self.assertEqual(dropped, 1)
        self.assertEqual([item["link"] for item in kept], ["https://b.test/2", "https://c.test/3"])

    def test_near_identical_titles_are_merged(self):
        items = [
            _item("SK海力士三季度营收创历史新高", link="https://a.test/1"),
            _item("SK海力士三季度营收创历史新高！", link="https://b.test/2"),
        ]
        self.assertEqual(dedupe.dedupe(items)[1], 1)

    def test_different_stories_are_kept(self):
        items = [
            _item("台积电2nm量产进度", link="https://a.test/1"),
            _item("中芯国际扩产计划", link="https://b.test/2"),
        ]
        kept, dropped = dedupe.dedupe(items)
        self.assertEqual((len(kept), dropped), (2, 0))

    def test_same_title_days_apart_is_not_merged(self):
        # 系列报道常复用同一标题（每日盘面复盘），相隔太久不能合并。
        items = [
            _item("国内要闻", link="https://a.test/1", published="2026-11-01T08:00:00+08:00"),
            _item("国内要闻", link="https://b.test/2", published="2026-11-20T08:00:00+08:00"),
        ]
        self.assertEqual(dedupe.dedupe(items)[1], 0)

    def test_missing_publish_time_still_merges(self):
        items = [
            _item("某稿件", link="https://a.test/1"),
            _item("某稿件", link="https://b.test/2", published="2026-11-20T08:00:00+08:00"),
        ]
        self.assertEqual(dedupe.dedupe(items)[1], 1)


if __name__ == "__main__":
    unittest.main()
