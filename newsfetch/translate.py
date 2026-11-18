"""英译中：仅在配置了 Google Cloud Translation 凭据时启用。"""

from __future__ import annotations

import logging
import os

import requests

from config import TIMEOUT_SECONDS
from newsfetch import http

LOGGER = logging.getLogger("newsfetch.translate")
ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
MAX_CHUNK = 20_000


def _translate_text(api_key: str, value: str) -> str | None:
    chunks = [value[index : index + MAX_CHUNK] for index in range(0, len(value), MAX_CHUNK)] or [""]
    translated: list[str] = []
    for chunk in chunks:
        try:
            response = http.session().post(
                ENDPOINT,
                params={"key": api_key},
                json={"q": [chunk], "target": "zh-CN", "format": "text"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            translated.append(str(response.json()["data"]["translations"][0]["translatedText"]))
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            LOGGER.warning("翻译失败: %s", exc)
            return None
    return "".join(translated)


def to_chinese(values: list[str]) -> list[str]:
    """批量翻译为中文；未配置凭据或失败时返回原文。"""
    api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
    if not api_key or not values:
        return values
    result: list[str] = []
    for value in values:
        translated = _translate_text(api_key, value)
        result.append(translated if translated else value)
    return result
