"""工具脚本共用的凭据落盘工具。"""

from __future__ import annotations

import os
from pathlib import Path

# 微信 cookie / storage state 等同于账号会话，只允许当前用户读写。
PRIVATE_FILE_MODE = 0o600


def write_private_text(path: Path, text: str) -> None:
    """以 0600 权限写入文本文件。

    用 ``os.open`` 显式给出权限而不是 ``Path.write_text``，因为后者受进程 umask
    影响（常见 022 会得到 0644），同机其它用户即可读到会话凭据。

    Args:
        path: 输出路径；父目录必须已存在。
        text: 写入内容，按 UTF-8 编码。
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    # 已存在的文件不受 open 时的 mode 影响，这里再收紧一次。
    path.chmod(PRIVATE_FILE_MODE)
