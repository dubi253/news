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
    default_timezone: str | None = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
OUTPUT_PATH = DATA_DIR / "news.json"

TIMEOUT_SECONDS = 20
MAX_PER_FEED = 15
MAX_ITEMS = 160
MAX_CONTENT_LENGTH = 50_000
MAX_IMAGES_PER_ITEM = 5
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
        10,
    ),
    FeedConfig(
        "international",
        "The Guardian World",
        "https://www.theguardian.com/world/rss",
        5,
    ),
    FeedConfig(
        "international",
        "德国之声中文国际",
        "https://rss.dw.com/rdf/rss-chi-all",
        5,
    ),
    FeedConfig(
        "international",
        "联合早报国际",
        "https://plink.anyfeeder.com/zaobao/realtime/world",
        5,
    ),
    FeedConfig(
        "international",
        "纽约时报国际",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        5,
    ),
        # ============================================================
    # 2. Chinese Mainstream Media: 10
    # ============================================================
    # ---- 新华社 / 新华网（国家通讯社，第一优先级）----
    FeedConfig(
        "china",
        "新华社新闻",
        "https://feed.quanwenrss.com/feed/xinhua-yw.xml",
        10,
    ),
    FeedConfig(
        "china",
        "财富中文网",
        "https://feeder.co/discover/85dc2f2c3f/fortunechina-com",
        10,
    ),
    FeedConfig(
        "china",
        "联合早报中国",
        "https://plink.anyfeeder.com/zaobao/realtime/china",
        10,
    ),
    FeedConfig(
        "china",
        "人民日报",
        "https://plink.anyfeeder.com/people-daily",
        5,
    ),

    # ---- 中国新闻网（国家二级通讯社，官方原生 RSS 最完整）----
    # FeedConfig(
    #     "china",
    #     "中新网即时",
    #     "https://www.chinanews.com.cn/rss/scroll-news.xml",
    #     3,
    # ),
    # FeedConfig(
    #     "china",
    #     "中新网国际",
    #     "https://www.chinanews.com.cn/rss/world.xml",
    #     3,
    # ),
    # FeedConfig(
    #     "china",
    #     "中新网时政",
    #     "https://www.chinanews.com.cn/rss/china.xml",
    #     3,
    # ),
    # FeedConfig(
    #     "china",
    #     "中新网财经",
    #     "https://www.chinanews.com.cn/rss/finance.xml",
    #     3,
    # ),

    # ---- 央视 / 澎湃（视频与深度时政补充）----
    # FeedConfig(
    #     "china",
    #     "央视新闻",
    #     "https://plink.anyfeeder.com/cctv/news",
    #     3,
    # ),
    FeedConfig(
        "china",
        "澎湃新闻",
        "https://plink.anyfeeder.com/thepaper",
        10,
    ),

    FeedConfig(
        "social",
        "微博-热搜榜",
        "https://decemberpei.cyou/rssbox/weibo-realtimehot.xml",
        10,
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
        "Asia/Shanghai",
    ),
    FeedConfig(
        "technology",
        "GitHubDaily",
        "https://decemberpei.cyou/rssbox/wechat-githubdaily.xml",
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
        5,
    ),
    FeedConfig(
        "semiconductor",
        "IEEE Spectrum - Semiconductors",
        "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        5,
    ),
    FeedConfig("semiconductor", "Semiconductor Digest",
           "https://www.semiconductor-digest.com/feed/", 4),

    # ============================================================
    # 5. Semiconductor - Google News: 2
    # ============================================================
    FeedConfig(
        "semiconductor",
        "Google News - 晶圆代工与存储器",
        "https://news.google.com/rss/search?q=台积电+OR+三星代工+OR+英特尔代工+OR+中芯国际+OR+联电+OR+格芯+OR+华虹+OR+高塔半导体+OR+世界先进+OR+力积电+OR+SK海力士+OR+美光+OR+铠侠+OR+长鑫存储+OR+长江存储+OR+南亚科技+OR+华邦电子+OR+三星存储&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        4,
    ),

    FeedConfig(
        "semiconductor",
        "集微网",
        "https://decemberpei.cyou/rssbox/ijiwei.xml",
        10,
    ),

    FeedConfig(
        "semiconductor",
        "半导体行业观察",
        "https://decemberpei.cyou/rssbox/wechat-bandaotihangyeguancha.xml",
        6,
    ),

    FeedConfig(
        "semiconductor",
        "半导体芯闻",
        "https://decemberpei.cyou/rssbox/wechat-bandaotixinwen.xml",
        6,
    ),

    FeedConfig(
        "semiconductor",
        "芯榜上海",
        "https://decemberpei.cyou/rssbox/wechat-xinbangshanghai.xml",
        6,
    ),

    # ============================================================
    # 6. EDA / IP / Chip Design: 10
    # ============================================================
    FeedConfig(
        "semiconductor",
        "雷峰网 - 芯片",
        "https://www.leiphone.com/feed/categoryRss/name/chips",
        5,
    ),
    FeedConfig(
        "semiconductor",
        "SemiWiki",
        "https://semiwiki.com/feed/",
        2,
    ),

    # 8. AI Compute / AI Infrastructure: 11
    # ============================================================
    FeedConfig(
        "ai_infra",
        "SemiAnalysis",
        "https://newsletter.semianalysis.com/feed",
        5,
    ),
    FeedConfig(
        "ai_infra",
        "ServeTheHome",
        "https://www.servethehome.com/feed/",
        4,
    ),
    
    FeedConfig(
        "semiconductor",
        "Google News - Foundry and Memory",
        "https://news.google.com/rss/search?q=TSMC+OR+%22Samsung+Foundry%22+OR+%22Intel+Foundry%22+OR+SMIC+OR+UMC+OR+GlobalFoundries+OR+%22Hua+Hong%22+OR+%22Tower+Semiconductor%22+OR+VIS+OR+PSMC+OR+X-FAB+OR+%22DB+HiTek%22+OR+%22SK+Hynix%22+OR+Micron+OR+Kioxia+OR+CXMT+OR+YMTC+OR+%22Nanya%22+OR+%22Winbond%22+OR+%22Samsung+Memory%22&hl=en-US&gl=US&ceid=US:en",
        4,
    ),
)

