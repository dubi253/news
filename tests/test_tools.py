"""工具脚本的凭据落盘行为测试。"""

import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.credentials import write_private_text


class WritePrivateTextTests(unittest.TestCase):
    def test_new_file_is_owner_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cookie.txt"
            write_private_text(path, "wxuin=1; wxsid=2")

            self.assertEqual(path.read_text(encoding="utf-8"), "wxuin=1; wxsid=2")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_world_readable_file_is_tightened(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o644)

            write_private_text(path, '{"cookies": []}')

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_text(encoding="utf-8"), '{"cookies": []}')

    def test_rewrite_truncates_previous_content(self):
        # 会话凭据可能变短，残留的旧字节会把 JSON 破坏掉。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_private_text(path, "x" * 500)
            write_private_text(path, "short")

            self.assertEqual(path.read_text(encoding="utf-8"), "short")


if __name__ == "__main__":
    unittest.main()
