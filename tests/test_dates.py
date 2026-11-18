"""时间戳解析测试：重点覆盖发布方把本地时间标成 GMT 的情况。"""

import unittest
from datetime import UTC, datetime

from newsfetch import dates


class PublishedTimeTests(unittest.TestCase):
    def test_preserves_declared_offset(self):
        entry = {"published": "Mon, 16 Nov 2026 14:00:00 +0800"}
        self.assertEqual(dates.published_time(entry), "2026-11-16T14:00:00+08:00")

    def test_configured_zone_overrides_wrong_gmt_label(self):
        # InfoQ 的 pubDate 是北京时间却标成 GMT，必须按东八区解读。
        entry = {"published": "Wed, 18 Nov 2026 18:59:07 GMT"}
        self.assertEqual(
            dates.published_time(entry, "Asia/Shanghai"),
            "2026-11-18T18:59:07+08:00",
        )

    def test_naive_timestamp_without_zone_is_dropped(self):
        self.assertEqual(dates.published_time({"published": "2026-11-16T14:00:00"}), "")

    def test_naive_timestamp_uses_configured_zone(self):
        entry = {"published": "2026-11-16T14:00:00"}
        self.assertEqual(
            dates.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_supports_rss_date_aliases(self):
        entry = {"date": "2026-11-16T14:00:00"}
        self.assertEqual(
            dates.published_time(entry, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_struct_time_is_treated_as_utc(self):
        # feedparser 的 *_parsed 已归一化为 UTC。
        parsed = datetime(2026, 11, 16, 6, 0, 0, tzinfo=UTC).timetuple()
        self.assertEqual(
            dates.published_time({"published_parsed": parsed}, "Asia/Shanghai"),
            "2026-11-16T14:00:00+08:00",
        )

    def test_invalid_value_returns_empty(self):
        self.assertEqual(dates.published_time({"published": "not a date"}), "")

    def test_sort_key_compares_instants(self):
        later = {"published": "2026-11-16T06:00:00+00:00"}
        earlier = {"published": "2026-11-16T13:00:00+08:00"}
        self.assertGreater(dates.sort_key(later), dates.sort_key(earlier))


if __name__ == "__main__":
    unittest.main()
