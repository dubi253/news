"""应用配置：抓取参数、图片来源与订阅源清单。

本模块只存放常量与数据结构，不包含抓取逻辑，便于被各模块安全导入。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FeedConfig:
    """一个 RSS 订阅源的配置。

    Attributes:
        category: 产物中的分类字段。
        source: 产物中的来源名，也用于日志。
        url: 订阅地址；Google News 搜索页同样以 URL 形式给出。
        limit: 该源最多保留的条目数。
        timezone: 订阅源时间戳所在的时区。设置后会忽略订阅源自己声明的
            时区偏移，按该时区的墙上时间解读——用于把本地时间误标成 GMT
            的发布方（如 InfoQ）。
    """

    category: str
    source: str
    url: str
    limit: int = 8
    timezone: str | None = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
IMAGE_STAGING_DIR = DATA_DIR / ".images-staging"
OUTPUT_PATH = DATA_DIR / "news.json"
REPORT_PATH = DATA_DIR / "report.json"
# 上一轮快照：存在时用它复用未变化的条目，避免每轮重抓全文与图片。
PREVIOUS_PATH = DATA_DIR / "previous-news.json"
WECHAT_PROFILE_DIR = DATA_DIR / "wechat-browser"

TIMEOUT_SECONDS = 20
BROWSER_TIMEOUT_MS = 30_000
MAX_PER_FEED = 15
MAX_ITEMS = 160
# 订阅源之间的并发度。每个线程会各起一个 Chromium（约 150MB），
# 4 个并发在 16GB runner 上留足余量，同时把 34 个源的串行等待压掉大半。
FEED_WORKERS = 4
# 整轮抓取少于该条数时说明多数订阅源已经失效（反爬、网络或解析故障），
# 此时写快照会把线上好数据覆盖成残缺快照，直接失败退出更安全。
MIN_PUBLISH_ITEMS = 60
MAX_CONTENT_LENGTH = 50_000
MAX_IMAGES_PER_ITEM = 5
# 公众号文章配图密集，正文常有大图超过默认上限；单独放宽，其余来源不变。
MAX_IMAGES_PER_WECHAT_ITEM = 12
MAX_IMAGE_CANDIDATES = 12
MAX_IMAGE_BYTES = 15 * 1024 * 1024

# 正文抓取：短于该长度的正文视为摘要，需要回访原文。
MIN_ARTICLE_CHARS = 400
# 图片筛选：低于该分辨率的图片基本是图标、头像或站点素材。
MIN_IMAGE_WIDTH = 600
MIN_IMAGE_HEIGHT = 320
# 过窄或过扁的图片多为横幅、装饰条和二维码。
MIN_IMAGE_ASPECT = 0.35
MAX_IMAGE_ASPECT = 4.0
MIN_IMAGE_BYTES = 12_000

USER_AGENT = (
    # 固定为常见的 Windows Chrome UA：ua-generator 会给出 Linux/最新版本号，
    # 微信等站点会直接判为爬虫并返回验证页。
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}
# 订阅源用自己的身份抓：冒充浏览器但 TLS 指纹不像浏览器，会被
# Guardian 这类 WAF 直接 403（实测同一 IP 下 Chrome UA 403、订阅器 UA 200）。
FEED_HEADERS = {
    "User-Agent": "news-fetch/0.1 (+https://github.com/dubi253/news)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


FEEDS = (
    # ============================================================
    # 1. 国际新闻
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
        8,
    ),
    FeedConfig(
        "international",
        "联合早报国际",
        "https://plink.anyfeeder.com/zaobao/realtime/world",
        8,
    ),
    # FeedConfig(
    #     "international",
    #     "纽约时报国际",
    #     "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    #     4,
    # ),
    # ============================================================
    # 2. 中文主流媒体
    # ============================================================
    FeedConfig(
        "china",
        "新华社新闻",
        "https://feed.quanwenrss.com/feed/xinhua-yw.xml",
        10,
    ),
    FeedConfig(
        "china",
        "财富中文网",
        "https://plink.anyfeeder.com/fortunechina",
        5,
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
    FeedConfig(
        "china",
        "澎湃新闻",
        "https://plink.anyfeeder.com/thepaper",
        5,
    ),
    FeedConfig(
        "shanghai",
        "微信公众号-上海发布",
        "https://decemberpei.cyou/rssbox/wechat-shanghaifabu.xml",
        2,
    ),
    FeedConfig(
        "Knowledge",
        "微信公众号-地球知识局",
        "https://decemberpei.cyou/rssbox/wechat-diqiuzhishiju.xml",
        2,
    ),
    FeedConfig(
        "Knowledge",
        "微信公众号-星球研究所",
        "https://decemberpei.cyou/rssbox/wechat-xingqiuyanjiusuo.xml",
        2,
    ),
    FeedConfig(
        "Knowledge",
        "微信公众号-环球科学",
        "https://decemberpei.cyou/rssbox/wechat-huanqiukexue.xml",
        2,
    ),
    FeedConfig(
        "Knowledge",
        "微信公众号-丁香医生",
        "https://decemberpei.cyou/rssbox/wechat-dingxiangyisheng.xml",
        2,
    ),
    # ============================================================
    # 3. 通用科技
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
        # InfoQ 的 pubDate 把北京时间标成了 GMT，只能按东八区解读。
        "Asia/Shanghai",
    ),
    FeedConfig(
        "technology",
        "微信公众号-GitHubDaily",
        "https://decemberpei.cyou/rssbox/wechat-githubdaily.xml",
        5,
    ),
    # ============================================================
    # 4. 人工智能
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
    # 5. 半导体 - 全球
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
    FeedConfig(
        "semiconductor",
        "Semiconductor Digest",
        "https://www.semiconductor-digest.com/feed/",
        4,
    ),
    # ============================================================
    # 6. 半导体 - Google News 聚合
    # ============================================================
    FeedConfig(
        "semiconductor",
        "Google News - 晶圆代工与存储器",
        "https://news.google.com/rss/search?q=台积电+OR+三星代工+OR+英特尔代工+OR+中芯国际"
        "+OR+联电+OR+格芯+OR+华虹+OR+高塔半导体+OR+世界先进+OR+力积电+OR+SK海力士"
        "+OR+美光+OR+铠侠+OR+长鑫存储+OR+长江存储+OR+南亚科技+OR+华邦电子+OR+三星存储"
        "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
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
        "微信公众号-半导体行业观察",
        "https://decemberpei.cyou/rssbox/wechat-bandaotihangyeguancha.xml",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "微信公众号-半导体芯闻",
        "https://decemberpei.cyou/rssbox/wechat-bandaotixinwen.xml",
        6,
    ),
    FeedConfig(
        "semiconductor",
        "微信公众号-芯榜上海",
        "https://decemberpei.cyou/rssbox/wechat-xinbangshanghai.xml",
        6,
    ),
    # ============================================================
    # 7. EDA / IP / 芯片设计
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
    # ============================================================
    # 8. AI 算力 / 基础设施
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
        "https://news.google.com/rss/search?q=TSMC+OR+%22Samsung+Foundry%22"
        "+OR+%22Intel+Foundry%22+OR+SMIC+OR+UMC+OR+GlobalFoundries+OR+%22Hua+Hong%22"
        "+OR+%22Tower+Semiconductor%22+OR+VIS+OR+PSMC+OR+X-FAB+OR+%22DB+HiTek%22"
        "+OR+%22SK+Hynix%22+OR+Micron+OR+Kioxia+OR+CXMT+OR+YMTC+OR+%22Nanya%22"
        "+OR+%22Winbond%22+OR+%22Samsung+Memory%22&hl=en-US&gl=US&ceid=US:en",
        4,
    ),
)
