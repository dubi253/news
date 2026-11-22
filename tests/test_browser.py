"""浏览器层的线程隔离测试（不启动真实 Chromium）。

Playwright 的 sync API 不能在多个线程间共享同一个浏览器实例，并发抓取时每个
线程必须有自己的 Chromium；这里用假的 ``playwright.sync_api`` 验证复用与回收。
"""

import sys
import threading
import types
import unittest
from unittest.mock import patch

from newsfetch import browser


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self):
        self.chromium = types.SimpleNamespace(launch=self._launch)
        self.stopped = False

    @staticmethod
    def _launch(**kwargs):
        del kwargs  # 启动参数不参与断言
        return _FakeBrowser()

    def stop(self):
        self.stopped = True


class _FakeManager:
    def __init__(self, created):
        self.created = created

    def start(self):
        playwright = _FakePlaywright()
        self.created.append(playwright)
        return playwright


def _fake_module(created):
    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: _FakeManager(created)
    return module


class BrowserThreadTests(unittest.TestCase):
    def test_each_thread_gets_its_own_browser(self):
        created = []
        with patch.dict(sys.modules, {"playwright.sync_api": _fake_module(created)}):
            results = {}

            def worker(name):
                results[name] = browser._shared_browser()
                results[f"{name}-again"] = browser._shared_browser()

            threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertIsNot(results["a"], results["b"])
            # 同一线程内复用同一个实例，不会每篇文章重启浏览器。
            self.assertIs(results["a"], results["a-again"])
            self.assertEqual(len(created), 2)

            browser.close()

        self.assertTrue(all(playwright.stopped for playwright in created))
        self.assertTrue(results["a"].closed)
        self.assertEqual(browser._INSTANCES, [])

    def test_close_without_browser_is_noop(self):
        browser.close()


if __name__ == "__main__":
    unittest.main()
