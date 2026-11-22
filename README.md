# news

抓取分类新闻（RSS / Google News / 公众号镜像），回到原文取正文与配图，产出一份
`data/news.json` 与本地图片，供个人阅读器使用。

## 产物

| 路径 | 说明 |
| --- | --- |
| `data/news.json` | 阅读器契约：`updated` / `count` / `categories` / `items`（见 AGENTS.md） |
| `data/images/` | 正文配图，文件名是内容哈希前 16 位，同一张图只落盘一次 |
| `data/report.json` | 诊断附件：按订阅源统计条目数、空正文、无图、无时间与整源异常 |

主分支不跟踪 `data/`；每轮抓取的结果由 CI 发布到 `news` 分支（孤儿分支，force push，
只保留最新一份）。读取端可以直接取：

```text
https://raw.githubusercontent.com/dubi253/news/news/data/news.json
```

## 快速开始

```bash
uv sync                       # 依赖用 uv 管理，锁定在 uv.lock
uv run playwright install chromium   # 需要渲染的页面用 Playwright

uv run fetch.py                      # 全量抓取
uv run fetch.py --feed 雷峰 --verbose # 只抓来源名含“雷峰”的源，便于调试
uv run fetch.py --workers 1          # 串行抓取，排查并发相关问题
```

网络受限时可以用镜像装依赖（不要把镜像写进 `pyproject.toml`）：

```bash
UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ uv sync
```

## 环境变量

均为可选，缺省时对应能力自动跳过。

| 变量 | 用途 |
| --- | --- |
| `GOOGLE_TRANSLATE_API_KEY` | 英文标题与正文的英译中 |
| `WECHAT_COOKIE` / `WECHAT_STORAGE_STATE` / `WECHAT_PROXY` | 公众号登录态与代理 |
| `WECHAT_HEADFUL` / `WECHAT_MANUAL_VERIFY_TIMEOUT` | 本地人工过微信验证 |
| `NEWS_PREVIOUS_JSON` | 指定上一轮快照，用于复用未变化的条目（CI 用） |
| `NEWS_BROWSER_PROXY` | 浏览器渲染使用的代理 |

公众号登录态可以用 `uv run python tools/wechat_login.py` 在带图形界面的机器上获取，
产物写在 `data/`（已被 `.gitignore` 忽略）。

## 维护订阅源

订阅源清单与名额在 `config.py` 的 `FEEDS` 里，按分类分组；`FeedConfig.timezone` 只给
把本地时间误标成 GMT 的源使用。新增源不需要改抓取代码。

## 校验

```bash
uv run ruff format --check .
uv run ruff check .
uv run python -m unittest discover -s tests
uv run python -m newsfetch.report data/report.json   # 渲染本轮统计
```

测试不联网：HTTP、浏览器渲染、图片下载一律用 `unittest.mock.patch` 隔离。

## 已知限制

- **人民日报（paper.people.com.cn）**：每个文章页都内嵌同一张整版扫描图，页内图片
  无法区分“本稿配图”和“版面装饰”，因此宁可不发图，也不给同版所有文章挂同一张图。
- **集微网**：RSS 只给截断摘要且没有 `pubDate`，文章页也没有可解析的发布时间，
  产物里该字段为空串。
- **公众号**：数据中心 IP 容易命中验证页，需要有效的 `WECHAT_STORAGE_STATE`；
  会话与出口 IP 绑定，换网络后要重新获取。

## 相关文档

`AGENTS.md` 定义了产物契约、模块职责、抓取策略的既有结论与提交规范，改动前先读。
