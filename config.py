"""Application configuration for the news fetcher."""

from dataclasses import dataclass
from pathlib import Path

from ua_generator import generate
from ua_generator.options import Options


@dataclass(frozen=True, slots=True)
class FeedConfig:
    """Configuration for one RSS feed."""

    category: str
    source: str
    url: str
    limit: int = 8


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
OUTPUT_PATH = DATA_DIR / "news.json"

TIMEOUT_SECONDS = 20
MAX_PER_FEED = 8
MAX_ITEMS = 120
MAX_CONTENT_LENGTH = 50_000
MAX_IMAGES_PER_ITEM = 3
MAX_IMAGE_BYTES = 15 * 1024 * 1024
USER_AGENT = generate(device='desktop', browser='edge', platform='linux').text
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en,zh-CN;q=0.8",
}

FEEDS = (
    FeedConfig("international", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", 6),
    FeedConfig("international", "The Guardian World", "https://www.theguardian.com/world/rss", 6),
    FeedConfig("international", "德国之声中文", "https://rss.dw.com/rdf/rss-chi-all", 6),
    FeedConfig("international", "联合早报国际", "https://www.zaobao.com.sg/rss/realtime/world", 6),
    FeedConfig("technology", "TechCrunch", "https://techcrunch.com/feed/", 6),
    FeedConfig("technology", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab", 6),
    FeedConfig("technology", "36氪", "https://36kr.com/feed", 6),
    FeedConfig("technology", "爱范儿", "https://www.ifanr.com/feed", 6),
    FeedConfig("ai", "MIT AI", "https://news.mit.edu/rss/topic/artificial-intelligence2", 12),
    FeedConfig("ai", "QbitAI量子位", "https://www.qbitai.com/feed", 12),
    FeedConfig("ai", "机器之心", "https://www.jiqizhixin.com/rss", 12),
    FeedConfig("semiconductor", "Semiconductor Engineering", "https://semiengineering.com/feed/", 10),
    FeedConfig(
        "semiconductor",
        "IEEE Spectrum Semiconductors",
        "https://spectrum.ieee.org/rss/semiconductors/fulltext",
        8,
    ),
    FeedConfig(
        "semiconductor",
        "Semiconductor Today",
        "https://www.semiconductor-today.com/rss/news.xml",
        8,
    ),
    FeedConfig("semiconductor", "SemiWiki", "https://semiwiki.com/feed/", 8),
    FeedConfig("semiconductor", "EE Times", "https://www.eetimes.com/feed/", 8),
    FeedConfig("semiconductor", "Tom's Hardware", "https://www.tomshardware.com/feeds/all", 8),
    FeedConfig("semiconductor", "电子工程专辑", "https://www.eet-china.com/rss.xml", 8),
    FeedConfig("semiconductor", "SemiVoice 中文", "https://semivoice.com/feed.xml", 10),
)
