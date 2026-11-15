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
    # ============================================================
    # 1. International News
    # ============================================================
    FeedConfig(
        "international",
        "BBC World",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        6,
    ),
    FeedConfig(
        "international",
        "The Guardian World",
        "https://www.theguardian.com/world/rss",
        6,
    ),
    FeedConfig(
        "international",
        "德国之声中文",
        "https://rss.dw.com/rdf/rss-chi-all",
        6,
    ),
    FeedConfig(
        "international",
        "联合早报国际",
        "https://plink.anyfeeder.com/zaobao/realtime/world",
        6,
    ),

    # ============================================================
    # 2. General Technology
    # ============================================================
    FeedConfig(
        "technology",
        "TechCrunch",
        "https://techcrunch.com/feed/",
        6,
    ),
    FeedConfig(
        "technology",
        "Ars Technica",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        8,
    ),
    FeedConfig(
        "technology",
        "36氪",
        "https://www.36kr.com/feed",
        6,
    ),
    FeedConfig(
        "technology",
        "爱范儿",
        "https://www.ifanr.com/feed",
        5,
    ),
    FeedConfig(
        "technology",
        "InfoQ 中文",
        "https://www.infoq.cn/feed.xml",
        8,
    ),
    FeedConfig(
        "technology",
        "Tom's Hardware",
        "https://www.tomshardware.com/feeds/all",
        6,
    ),

    # ============================================================
    # 3. Artificial Intelligence
    # ============================================================
    FeedConfig(
        "ai",
        "MIT News - Artificial Intelligence",
        "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        8,
    ),
    FeedConfig(
        "ai",
        "量子位",
        "https://www.qbitai.com/feed",
        8,
    ),
    FeedConfig(
        "ai",
        "雷峰网 - AI",
        "https://www.leiphone.com/feed/categoryRss/name/ai",
        8,
    ),
    FeedConfig(
        "ai",
        "雷峰网 - AI 学术",
        "https://www.leiphone.com/feed/categoryRss/name/academic",
        6,
    ),

    # ============================================================
    # 4. Semiconductor - Global Industry & Technology
    # ============================================================
    FeedConfig(
        "semiconductor",
        "Semiconductor Engineering",
        "https://semiengineering.com/feed/",
        12,
    ),
    FeedConfig(
        "semiconductor",
        "IEEE Spectrum - Semiconductors",
        "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "Semiconductor Today",
        "https://www.semiconductor-today.com/rss/news.xml",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "EE Times",
        "https://www.eetimes.com/feed/",
        8,
    ),

    # ============================================================
    # 5. Semiconductor - Chinese Industry
    # ============================================================
    FeedConfig(
        "semiconductor",
        "雷峰网 - 芯片",
        "https://www.leiphone.com/feed/categoryRss/name/chips",
        8,
    ),
    FeedConfig(
        "semiconductor",
        "雷峰网 - 材料设备",
        "https://www.leiphone.com/feed/categoryRss/name/materials",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "雷峰网 - 晶圆代工",
        "https://www.leiphone.com/feed/categoryRss/name/manufacturing",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "雷峰网 - 封装测试",
        "https://www.leiphone.com/feed/categoryRss/name/packaging",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "芯师爷 - 半导体芯片",
        "http://www.gsi24.com/index/index/getrss/channel_id/4",
        8,
    ),
    FeedConfig(
        "semiconductor",
        "芯师爷 - 材料设备",
        "http://www.gsi24.com/index/index/getrss/channel_id/9",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "芯师爷 - 晶圆制造",
        "http://www.gsi24.com/index/index/getrss/channel_id/11",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "芯师爷 - 封装测试",
        "http://www.gsi24.com/index/index/getrss/channel_id/12",
        5,
    ),
    FeedConfig(
        "semiconductor",
        "芯师爷 - 行业报告",
        "http://www.gsi24.com/index/index/getrss/channel_id/19",
        4,
    ),

    # ============================================================
    # 6. EDA / IP / Chip Design
    # ============================================================
    FeedConfig(
        "eda_ip",
        "雷峰网 - 芯片设计",
        "https://www.leiphone.com/feed/categoryRss/name/chipdesign",
        8,
    ),
    FeedConfig(
        "eda_ip",
        "SemiWiki",
        "https://semiwiki.com/feed/",
        10,
    ),

    # ============================================================
    # 7. Memory - HBM / DRAM / NAND / Storage
    # ============================================================
    FeedConfig(
    "memory",
    "StorageNewsletter",
    "https://www.storagenewsletter.com/feed/",
        8,
    ),
    FeedConfig(
        "memory",
        "The Register",
        "https://www.theregister.com/headlines.atom",
        5,
    ),

    # ============================================================
    # 8. AI Compute / AI Infrastructure
    # ============================================================
    FeedConfig(
        "ai_infra",
        "SemiAnalysis",
        "https://newsletter.semianalysis.com/feed",
        8,
    ),
    FeedConfig(
        "ai_infra",
        "ServeTheHome",
        "https://www.servethehome.com/feed/",
        8,
    ),
    # ============================================================
    # International Foundry - TSMC / Samsung / Intel
    # ============================================================

    # Official company news
    FeedConfig(
        "foundry_global",
        "Samsung Semiconductor - Official",
        "https://news.samsung.com/global/category/products/semiconductors/feed",
        6,
    ),
    FeedConfig(
        "foundry_global",
        "Intel Newsroom - Google News",
        "https://news.google.com/rss/search?q=site%3Anewsroom.intel.com+semiconductor+OR+foundry&hl=en-US&gl=US&ceid=US:en",
        5,
    ),

    # TSMC - industry news aggregation
    FeedConfig(
        "foundry_global",
        "TSMC - Global News",
        "https://news.google.com/rss/search?q=TSMC+foundry&hl=en-US&gl=US&ceid=US:en",
        8,
    ),
    FeedConfig(
        "foundry_global",
        "TSMC - Process and Advanced Packaging",
        "https://news.google.com/rss/search?q=TSMC+2nm+OR+3nm+OR+CoWoS+OR+SoIC&hl=en-US&gl=US&ceid=US:en",
        6,
    ),

    # Samsung Foundry
    FeedConfig(
        "foundry_global",
        "Samsung Foundry - Global News",
        "https://news.google.com/rss/search?q=Samsung+Foundry+OR+Samsung+GAA&hl=en-US&gl=US&ceid=US:en",
        6,
    ),

    # Intel Foundry
    FeedConfig(
        "foundry_global",
        "Intel Foundry - Global News",
        "https://news.google.com/rss/search?q=Intel+Foundry+OR+Intel+18A+OR+Intel+14A&hl=en-US&gl=US&ceid=US:en",
        6,
    ),
)

