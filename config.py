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
MAX_ITEMS = 110
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
    # 1. International News: 12
    # ============================================================
    FeedConfig(
        "international",
        "BBC World",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        3,
    ),
    FeedConfig(
        "international",
        "The Guardian World",
        "https://www.theguardian.com/world/rss",
        3,
    ),
    FeedConfig(
        "international",
        "德国之声中文",
        "https://rss.dw.com/rdf/rss-chi-all",
        3,
    ),
    FeedConfig(
        "international",
        "联合早报国际",
        "https://plink.anyfeeder.com/zaobao/realtime/world",
        3,
    ),

    # ============================================================
    # 2. General Technology: 14
    # ============================================================
    FeedConfig(
        "technology",
        "TechCrunch",
        "https://techcrunch.com/feed/",
        4,
    ),
    FeedConfig(
        "technology",
        "Ars Technica",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        5,
    ),
    FeedConfig(
        "technology",
        "InfoQ 中文",
        "https://www.infoq.cn/feed.xml",
        5,
    ),

    # ============================================================
    # 3. Artificial Intelligence: 11
    # ============================================================
    FeedConfig(
        "ai",
        "MIT News - Artificial Intelligence",
        "https://news.mit.edu/rss/topic/artificial-intelligence2",
        4,
    ),
    FeedConfig(
        "ai",
        "雷峰网 - AI",
        "https://www.leiphone.com/feed/categoryRss/name/ai",
        4,
    ),
    FeedConfig(
        "ai",
        "雷峰网 - 顶会专区",
        "https://www.leiphone.com/feed/categoryRss/name/private",
        3,
    ),

    # ============================================================
    # 4. Semiconductor - Global: 18
    # ============================================================
    FeedConfig(
        "semiconductor",
        "Semiconductor Engineering",
        "https://semiengineering.com/feed/",
        10,
    ),
    FeedConfig(
        "semiconductor",
        "IEEE Spectrum - Semiconductors",
        "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        4,
    ),
    FeedConfig("semiconductor", "Semiconductor Digest",
           "https://www.semiconductor-digest.com/feed/", 4),

    # ============================================================
    # 5. Semiconductor - Chinese: 12
    # ============================================================
    FeedConfig(
        "semiconductor",
        "雷峰网 - 材料设备",
        "https://www.leiphone.com/feed/categoryRss/name/materials",
        4,
    ),
    FeedConfig(
        "semiconductor",
        "雷峰网 - 晶圆代工",
        "https://www.leiphone.com/feed/categoryRss/name/manufacturing",
        5,
    ),
    FeedConfig(
        "semiconductor",
        "雷峰网 - 封装测试",
        "https://www.leiphone.com/feed/categoryRss/name/packaging",
        3,
    ),

    # ============================================================
    # 6. EDA / IP / Chip Design: 10
    # ============================================================
    FeedConfig(
        "eda_ip",
        "雷峰网 - 芯片设计",
        "https://www.leiphone.com/feed/categoryRss/name/chipdesign",
        5,
    ),
    FeedConfig(
        "eda_ip",
        "SemiWiki",
        "https://semiwiki.com/feed/",
        5,
    ),

    # ============================================================
    # 7. Memory - HBM / DRAM / NAND: 5
    # ============================================================
    FeedConfig(
        "memory",
        "StorageNewsletter",
        "https://www.storagenewsletter.com/feed/",
        5,
    ),

    # ============================================================
    # 8. AI Compute / AI Infrastructure: 11
    # ============================================================
    FeedConfig(
        "ai_infra",
        "SemiAnalysis",
        "https://newsletter.semianalysis.com/feed",
        7,
    ),
    FeedConfig(
        "ai_infra",
        "ServeTheHome",
        "https://www.servethehome.com/feed/",
        4,
    ),

    # ============================================================
    # 9. International Foundry - TSMC / Samsung / Intel: 7
    # ============================================================
    FeedConfig(
        "foundry_global",
        "Samsung Newsroom - Official",
        "https://news.samsung.com/global/?feed=rss2",
        2,
    ),
    FeedConfig(
        "foundry_global",
        "Global Foundry News - TSMC / Samsung / Intel",
        "https://news.google.com/rss/search?q=TSMC+OR+%22Samsung+Foundry%22+OR+%22Intel+Foundry%22+OR+%22Intel+18A%22&hl=en-US&gl=US&ceid=US:en",
        5,
    ),
)

