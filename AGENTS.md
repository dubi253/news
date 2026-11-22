# AGENTS.md

## 目标

本仓库抓取分类新闻（RSS / Google News），回到原文取正文与配图，产出一份
`data/news.json` 和本地图片，供个人阅读器使用。代码应保持高内聚、低耦合，便于
测试与长期维护；新增能力优先复用成熟开源库，不做重复实现。

## 产物契约（不得随意破坏）

`data/news.json`：

```json
{
  "updated": "ISO8601 UTC",
  "count": 123,
  "categories": ["ai", "china", "..."],
  "items": [
    {
      "category": "technology",
      "source": "InfoQ 中文",
      "title": "...",
      "language": "zh",
      "published": "ISO8601 带偏移，无法判断时为空串",
      "link": "原文地址",
      "content": "纯文本 Markdown，不含图片语法",
      "images": ["data/images/<sha256前16位>.<ext>"]
    }
  ]
}
```

- 图片只出现在 `images` 里，正文不内嵌图片语法。
- 字段只增不改；改变字段语义必须在提交说明中写明。
- 图片文件名由内容哈希决定，同一张图不会重复落盘；每轮结束按产物引用清理
  目录（产物之外的图片一律删除），因此复用上一轮的图片不会留下孤儿文件。
- `data/report.json` 是诊断附件，不属于阅读器契约：按订阅源记录条目数、
  空正文、无图、无时间与整源异常，供 CI job summary 与排障使用。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `config.py` | 参数常量与订阅源清单，不含抓取逻辑 |
| `fetch.py` | 命令行入口、订阅源并发遍历、发布守门、快照原子写入 |
| `newsfetch/feeds.py` | RSS 条目 → 产物条目（正文、图片、语言、时间） |
| `newsfetch/http.py` | 会话、重试、反爬识别、浏览器升级 |
| `newsfetch/browser.py` | Playwright 渲染，线程内共用一个 Chromium |
| `newsfetch/extract.py` | 正文抽取（trafilatura 为主）与 Markdown 归一 |
| `newsfetch/images.py` | 候选收集、分辨率筛选、去重、下载 |
| `newsfetch/wechat.py` | 公众号文章（解析库 → 登录态浏览器） |
| `newsfetch/googlenews.py` | Google News RSS 与跳转链接还原 |
| `newsfetch/article.py` | 单篇文章的多级抓取与正文质量判断 |
| `newsfetch/dates.py` | 时间戳解析与时区处理 |
| `newsfetch/text.py` | 编码识别、乱码修复、语种判断 |
| `newsfetch/translate.py` | 可选英译中 |
| `newsfetch/dedupe.py` | 跨源同一稿件的标题去重 |
| `newsfetch/report.py` | 每轮分源统计与 CI 汇总渲染 |

模块之间通过 `newsfetch/models.py` 中的数据结构（`NewsItem`、`Candidate`、`Article`）传递结果，
不依赖隐式全局状态；`http` 可以向 `browser` 单向依赖，反向不允许。`NewsItem` 是
`data/news.json` 字段契约的类型化描述，改字段时它与本文件同步修改。

## 抓取策略上的既有结论

- **User-Agent 固定为 Windows Chrome**。生成 Linux 或最新版本号的 UA 会被微信直接
  判为爬虫并返回验证页；不要为了“更真实”再引入随机 UA。
- **反爬分层**：requests → 命中 403/429/验证页/近乎空 HTML → Playwright 渲染。
  判定条件与标记集中在 `http.py`，不要在业务代码里散落字符串判断。
- **订阅源时区**：多数源给出正确的偏移，直接保留；只有把本地时间误标成 GMT 的源
  （如 InfoQ）才在 `FeedConfig.timezone` 里指定墙上时区，一旦设置就忽略其声明偏移。
- **正文判定**：短于 `MIN_ARTICLE_CHARS` 视为摘要，需要回访原文；抽取结果若只是
  导航碎片或登录墙，宁可留空也不写进产物。
- **公众号发布时间**：rssbox 镜像的 RSS 条目没有 `pubDate`，发布时间取文章页脚本里的
  `var ct` / `var oriCreateTime`（Unix 时间戳，按东八区输出）；RSS 自带时间时以 RSS 为准。
- **图片门槛**：像素尺寸、宽高比、字节数三项同时达标才算正文大图；同一张图的不同
  分辨率按归一化 URL 去重，只保留最大的一份。阈值放在 `config.py`。公众号文章配图
  密集，用 `MAX_IMAGES_PER_WECHAT_ITEM` 单独放宽，其他来源仍用 `MAX_IMAGES_PER_ITEM`。

- **回访原文的判定**：摘要被截断、正文过短、`rank()` 之后没有可用大图、没有发布
  时间，四条命中任一即回访；如果首次下载后一张图都不达标，还会再回访一次（每篇
  最多一次）。只判"候选列表为空"不够——RSS 摘要里的图标级 `<img>` 会让它永远
  成立不了。
- **发布守门**：整轮少于 `MIN_PUBLISH_ITEMS` 条，或不足线上快照的一半时直接失败
  退出，不写快照。news 分支是孤儿分支 + force push，没有历史可回滚，坏数据覆盖
  即永久丢失。`--feed` 调试入口不受此限制。
- **并发**：订阅源之间用 `ThreadPoolExecutor` 并发（`FEED_WORKERS`，可用
  `--workers` 调整）；Playwright 的 sync API 不能跨线程共享浏览器，因此浏览器
  实例按线程隔离并登记，`close()` 统一回收。`pool.map` 保序，输出与串行一致。
- **复用上一轮快照**：`data/previous-news.json`（CI 从 news 分支还原）命中时，链接
  与标题都没变、正文够长、图片仍在本地且非空的条目直接复用，不再回访原文。
  无图条目一律重抓，避免把缺陷固化。
- **跨源去重**：链接去重之后，按归一化标题 + 相似度 ≥0.9 + 发布时间相差 48 小时内
  合并同一稿件，保留有图、正文更长的一条，位置取首次出现。
- **分类配额**：`MAX_ITEMS` 不是单纯按时间截断，而是先给每个分类
  `MAX_ITEMS / 分类数` 的保底名额，富余名额再按时间补满。

## 设计与代码风格

- Python 遵守 [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)。
- 命名表达意图；一个函数只做一件事，超过 50 行应拆分；单个文件不超过 500 行。
- 不使用裸 `except`；异常在能处理的位置处理，并保留上下文。
- 注释解释“为什么”和约束，不重复代码本身；公共函数必须有 docstring。
- 禁止重复造轮子：正文抽取用 trafilatura、HTML→Markdown 用 markdownify、图片尺寸
  用 Pillow、Google News 链接还原用 googlenewsdecoder、公众号解析用
  wechat-article-parser。新增依赖前先确认现有库是否已覆盖。
- 不提交调试输出、未使用导入、注释掉的死代码、硬编码凭据。

## 依赖与环境

- Python 3.15.2（`.python-version`），依赖用 `uv` 管理，`uv.lock` 必须提交且
  指向 `https://pypi.org/simple`（CI 用官方源）。
- 本地网络受限时用镜像解析，但**不要**把镜像地址写进 `pyproject.toml`：

  ```bash
  UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ uv sync
  ```

- 需要渲染的页面要装浏览器：`uv run playwright install chromium`。
- 格式化与静态检查：`uv run ruff format .`、`uv run ruff check .`。

## 测试与验证

- 行为变化必须补测试，覆盖边界与失败路径；测试验证公开行为，不依赖实现细节。
- 测试不联网：HTTP、浏览器、图片下载一律通过 `unittest.mock.patch` 隔离。
- 提交前至少跑：

  ```bash
  uv run ruff format --check .
  uv run ruff check .
  uv run python -m unittest discover -s tests
  uv run python fetch.py --feed InfoQ   # 可选：小范围真实抓取验证
  ```

- CI（`.github/workflows/news.yml`）会跑同样的三项检查，再抓取并发布快照。

## 提交规范（中文约定式提交）

格式：`<type>(<scope>): <中文描述>`，一行不超过 72 字；需要说明原因时留空行再写正文。

| type | 用途 |
| --- | --- |
| `feat` | 新增能力（新源、新字段、新抓取能力） |
| `fix` | 修复缺陷（时区、正文缺失、图片错筛等） |
| `refactor` | 不改变产物的结构调整 |
| `perf` | 性能优化 |
| `chore` | 依赖、CI、配置等杂项 |
| `docs` | 仅文档 |
| `test` | 仅测试 |

约定：

- 描述用中文，祈使句，不加句号；`scope` 用模块名或订阅源名，例如
  `fix(images): 只保留同一张图的最高清版本`。
- **每次改动都要提交**：改完（含仅文档、仅测试的改动）即按本节格式落成提交，
  不把改动留在工作区；除非用户在当次明确要求先不提交。
- 一个提交只做一件事；重构与行为修复分开提交，便于回滚。
- 破坏产物契约或改变抓取语义时，在正文中写明影响范围和迁移方式。
- 不提交生成物以外的临时文件；`data/` 下的快照由 CI 发布到 `news` 分支。

## 变更要求

- 先读调用链再改；改动范围最小化，不做顺手重构。
- 修改公共接口时同步更新所有调用方、测试与本文档。
- 提交前核对 `git diff`，确认没有临时文件、敏感信息或无关格式化，然后按《提交规范》提交。
