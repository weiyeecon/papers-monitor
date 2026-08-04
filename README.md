# 数字货币与金融稳定 · 工作论文自动监测

每周一自动抓取 **NBER、CEPR、BIS、IMF、各国央行、国际组织** 共 31 个官方 feed，
筛出与 **稳定币 / 加密资产 / 资产代币化 / CBDC / 金融稳定 / 跨境支付** 相关的新论文，
用 Anthropic API 生成结构化中文摘要，产出两样东西：

- **网页看板** `docs/index.html` —— 可按主题、机构、时间窗筛选，支持中文搜索、MD/CSV 导出
- **Markdown 周报** `reports/YYYY-Www.md` —— 手机上用 GitHub App 就能读

抓取跑在 GitHub Actions 的服务器上，没有浏览器同源策略，**不需要任何 CORS 代理**。

---

## 部署（三步，约五分钟）

### 1. 建仓库

把本目录全部内容推到一个新仓库：

```bash
git init
git add .
git commit -m "init: 论文监测"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

不想用命令行的话，在 GitHub 网页上新建仓库后点 **Add file → Upload files**，
把这些文件夹整个拖进去也一样（注意 `.github` 是隐藏文件夹，用命令行更稳）。

### 2. 配置

在仓库 **Settings** 里做三件事：

| 位置 | 要做什么 | 说明 |
|---|---|---|
| Secrets and variables → Actions → **New repository secret** | 名字填 `DEEPSEEK_API_KEY`，值填你的 key | 三选一，见下表；不填也能跑，只是没有中文摘要 |
| Actions → General → Workflow permissions | 选 **Read and write permissions** | **必须改**，否则 Action 无法把结果 commit 回仓库 |
| Pages → Build and deployment | Source 选 **Deploy from a branch**，分支 `main`、目录 **`/(root)`** | 私有仓库需要 GitHub Pro 才能开 Pages |

#### 用哪家模型：Secret 名字三选一

配了哪个就用哪个，同时配多个按下表从上到下取第一个。

| Secret 名字 | 走哪家 | 默认模型 | 备注 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek | `deepseek-v4-flash` | 最便宜，中文最顺，国内充值方便 |
| `LLM_API_KEY` | 任意 OpenAI 兼容服务 | 需自己指定 | 必须同时设 `LLM_BASE_URL`，见下 |
| `ANTHROPIC_API_KEY` | Anthropic 原生接口 | `claude-haiku-4-5` | |

`LLM_API_KEY` 这条通吃 Kimi、通义千问兼容模式、智谱、硅基流动、OpenRouter、
OpenAI 本身等所有提供 `/chat/completions` 的服务，只要在 Variables 里填上
`LLM_BASE_URL`（例如 `https://api.moonshot.cn/v1`）和 `LLM_MODEL` 即可。

可选（Variables 标签页，不是 Secrets）：

- `LLM_MODEL` —— 覆盖默认模型。**写错不要紧**：程序会先向服务端 `/models` 校验，
  模型不存在或已下线时自动挑一个可用的小模型顶上，不会让整场跑挂掉。
  （比如 DeepSeek 的 `deepseek-chat` 已于 2026-07-24 下线，填了会自动换成 `deepseek-v4-flash`。）
- `LLM_BASE_URL` —— 自定义接口地址。用 DeepSeek 或 Anthropic 时留空即可。
- `ANTHROPIC_MODEL` —— 只在走 Anthropic 时生效。
- `OPENALEX_MAILTO` —— 填你的邮箱，OpenAlex 会给更高的速率配额（用于给 IMF 论文补摘要）。

### 3. 先手动跑一次

Actions → **weekly-fetch** → **Run workflow**。
跑完大约 3–8 分钟，回到仓库能看到新增的 `docs/data.json` 和 `reports/`。
之后每周一 UTC 11:00（美东早上 7 点）自动跑。

首次运行会把当前所有源上能抓到的相关论文都翻译一遍，受 `TRANSLATE_LIMIT`（默认 60 篇/次）
限制，可能要连跑两三次才补齐；之后每周只翻新增的那几十篇。

---

## 目录

```
sources.json       31 个数据源（机构、feed 地址、解析方式）
taxonomy.json      主题词典、数据源词典、方法词典、中文检索映射
fetch_feeds.py     抓取与解析（RSS/Atom/RDF + NBER/Crossref/World Bank 三个 JSON 接口）
analyse.py         主题识别、相关度打分、数据与方法提取（纯规则，不调模型）
translate.py       中文摘要，支持 DeepSeek / Anthropic / 任意 OpenAI 兼容服务，只翻新增
build.py           产出 data.json 与 reports/*.md
run.py             主流程
index.html         看板页面（GitHub Pages 的入口）
app.js             看板逻辑
```

运行后自动生成、由 Actions 提交回仓库的：

```
papers.json        累积库（去重后的全量条目，含中文摘要，随仓库增长）
data.json/data.js  看板读的数据（data.js 是给 file:// 直接打开时用的）
reports/           每周 Markdown 简报，latest.md 恒指向最新一期
```

> 全部文件平铺在仓库根目录，没有子文件夹——这样在 GitHub 网页上传时可以直接多选拖拽。
> 唯一的例外是 `.github/workflows/weekly.yml`，它必须在那个路径下，用网页版
> 「Create new file」输入带斜杠的路径即可创建。
>
> **`app.js` 不要改成 `_app.js` 之类下划线开头的名字。** GitHub Pages 默认跑 Jekyll，
> 会把下划线开头的文件当成模板素材而不发布，页面会因为加载不到脚本而白屏。


### 本地跑

```bash
pip install -r requirements.txt
DEEPSEEK_API_KEY=sk-... python run.py
open index.html               # 直接双击也能开，页面会读同目录的 data.js
```

---

## 改源、改主题

**加一个机构**：往 `sources.json` 的 `sources` 里加一条：

```json
{ "id": "riksbank", "org": "Riksbank", "cn": "瑞典央行", "group": "cb",
  "ptype": "Working Paper", "kind": "rss",
  "url": "https://example.org/feed.xml" }
```

`kind` 取 `rss`（RSS/Atom/RDF 都归它）、`nber`、`crossref`、`worldbank`。
`group` 取 `core` / `cb` / `intl`，对应看板上的机构筛选钮。

**改主题范围**：编辑 `taxonomy.json` 的 `topics[].kw`。
关键词全部小写，程序会在标题和摘要里做子串匹配——标题命中权重是摘要的 3.5 倍。
`data_dict` 和 `method_dict` 决定"用了什么数据、什么方法"那两行怎么识别，
想加自己领域的数据库（比如某个链上数据商）直接往里加一行即可。

**改跑的时间**：`.github/workflows/weekly.yml` 里的 cron，注意它是 UTC。

---

## 成本

每周新增的主题相关论文一般是 20–50 篇，每篇约 1.5k 输入 token + 0.4k 输出 token，
一周合计大约 5 万输入 + 1.5 万输出。历史条目不会重复翻译。

按 DeepSeek 官方公开价目（`deepseek-v4-flash`：输入未命中缓存 $0.14/百万、输出 $0.28/百万）
粗算，**一周约 1 美分，一年一美元出头**。注意官方另有"高峰时段翻倍"政策（北京时间
9–12 点、14–18 点），本项目默认在 UTC 11:00 也就是北京时间 19:00 跑，不在高峰窗口内。
价格以你查询时的官方页面和账单为准。

如果某周源站集中补发大量历史条目，`TRANSLATE_LIMIT` 会兜住上限，剩下的顺延到下周
（按相关度排序，最该看的那些优先翻）。

---

## 已知边界

写在前面，免得你以为覆盖率比实际更高：

- **IMF 没有可用的 RSS 了**。官方 Publications 页已不再声明任何 feed，
  旧的 `imf.org/external/rss/rsslist.aspx` 返回 403。这里改走 Crossref 的 IMF DOI
  前缀 `10.5089`，题录和日期可靠，但 IMF 往往不向 Crossref 提交摘要——
  程序会再用 DOI 去 OpenAlex 补一次摘要，仍有一部分补不到，那些卡片只有标题。
- **BIS 的 robots.txt 对 `/doclist/` 是 Disallow**。这些地址是 BIS 自己在
  [bis.org/rss/index.htm](https://www.bis.org/rss/index.htm) 上作为订阅入口公布的，
  本项目按普通 RSS 订阅的方式每周读一次、带可识别的 User-Agent。
  如果你所在机构对此有更严格的合规要求，把 `sources.json` 里 5 个 `bis.org`
  的源删掉即可，其余部分不受影响。
- **没收进来的**：IOSCO 的 RSS 停更在 2023 年、波士顿联储停在 2020 年、
  纽约联储 Staff Reports 的 feed 停在 2015 年（改用了 Liberty Street 博客替代）；
  OECD 和 FATF 官网没有提供任何 RSS/Atom。这些宁可不放，也不给你虚假的覆盖感。
- **BoE、Bundesbank、BoJ、HKMA 的 feed 不含摘要**，只有标题和链接。
  这类条目的中文摘要是模型依据标题作的概括，"数据/方法"两行会写"摘要未提供"。
- **主题筛选是关键词规则**，不是语义理解。宁可放宽也不漏——所以看板上会有少量
  只是顺带提了一句 blockchain 的论文。觉得某类噪音太多，就去 `taxonomy.json` 收紧对应词条。

## 数据来源

所有条目均来自各机构官方公开的 RSS/Atom feed 或公开 API，仅保存题录信息与摘要，
链接一律指向机构原文页面。
