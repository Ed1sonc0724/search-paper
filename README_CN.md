<h1 align="center">Search Papers</h1>

<p align="center">
  <b>AI 学术论文搜索助手</b><br>
  跨平台文献检索工具，支持 <b>国内外任意高校</b><br>
  内置 <b>LLM Wiki</b>，把文献检索沉淀为长期科研知识库<br>
  集成 arXiv · CrossRef · Scopus · PubMed 四大数据库，DeepSeek AI 智能分析
</p>

<p align="center">
  <a href=#-特色功能>特色功能</a> •
  <a href=#-快速开始>快速开始</a> •
  <a href=#-使用方法>使用方法</a> •
  <a href=#-llm-wiki-一体化>LLM Wiki</a> •
  <a href=#-配置说明>配置说明</a> •
  <a href=#-命令参考>命令参考</a> •
  <a href=#-常见问题>常见问题</a> •
  <a href="README.md">English</a>
</p>

---

## 这是什么？

**Search Papers** 是一个终端运行的学术文献搜索工具，能同时查询 **arXiv、CrossRef、Scopus、PubMed** 四个数据库，并利用 **DeepSeek AI** 对搜索结果进行智能分析、排序和解读。支持递归引用追踪（深度搜索）、通过校园网/VPN 自动下载论文 PDF，并在 [`wiki/`](wiki/) 中内置一套 **LLM Wiki**，用于把检索结果沉淀为可长期维护的科研知识库。

### LLM Wiki 一体化

本仓库已经包含 [`wiki/`](wiki/) 骨架，面向固态电池多物理场耦合研究场景。检索工具和 Wiki 是一条完整链路：

1. 在 CLI 中检索、排序、分析论文。
2. 执行 `ingest <N>` 下载 PDF，并在 `wiki/sources/literature/` 生成文献元数据桩。
3. 将 `wiki_bridge.py` 生成的 prompt 交给 LLM agent。
4. Agent 按 [`wiki/CLAUDE.md`](wiki/CLAUDE.md) 规范补全文献页、实体页、概念页、双向链接、索引和日志。

`wiki/raw/` 用于保存原始 PDF 和科研资产，默认不纳入 git；Markdown 知识页面会随代码一起版本化，形成一体化的检索与知识积累系统。

### 解决什么问题？

| 痛点 | Search Papers 方案 |
|------|-------------------|
| 多个数据库分散查询 | 4 个数据源并行搜索 |
| 关键词总搜不准 | AI 自动优化为学术检索词 |
| 论文太多不知先看哪篇 | 1-5 星推荐指数 + 相关性打分 |
| 读论文太慢抓不住重点 | AI 生成专属阅读指南 |
| 付费论文下不到 PDF | 通过校园网 IP/VPN 自动下载 |
| 想追踪引用链太麻烦 | 深度搜索递归追踪引用文献 |
| 搜完之后笔记分散 | 内置 LLM Wiki，把摄入论文变成双向链接的 Markdown 知识库 |

---

## 特色功能

- **多源并行搜索** — arXiv、CrossRef、Scopus、PubMed 同时查询
- **AI 查询优化** — DeepSeek 将你的主题转化为精准英文学术检索词
- **智能推荐排序** — 综合相关性(50%)、引用数(25%)、时效性(15%)、来源质量(10%) 的四维评分
- **AI 分析报告** — 结构化综述：论文分类、研究趋势、Top-5 推荐
- **单篇深度解读** — AI 生成专属阅读指南（研究空白、方法、发现、局限性）
- **多篇对比分析** — 最多 5 篇论文交叉对比，找共同主线与互补关系
- **引用深度搜索** — 递归追踪引用链，最多 5 层
- **PDF 自动下载** — 三阶段策略：arXiv 直链 → DOI/HTML 解析(校园网) → Unpaywall OA → Selenium 兜底
- **精美终端界面** — Rich 驱动的表格、面板、Markdown 渲染
- **LLM Wiki 一体化** — 内置 `wiki/` 骨架，包含文献页、实体页、概念页、综合分析页和 LLM 维护规范

---

## 快速开始

### 环境要求

- **Python 3.10+**（推荐 3.12）
- **DeepSeek API Key**（[免费获取](https://platform.deepseek.com/api_keys)）

### 安装

```bash
# 克隆项目
git clone https://github.com/Ed1sonc0724/search-paper.git
cd search-paper

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY

# 启动
python app.py
```

### Pipenv 方式

```bash
pip install pipenv
pipenv install
pipenv run python app.py
```

### 首次搜索

```text
📎 输入命令 search 固态电解质界面
```

AI 会自动优化查询词、搜索四个数据库、排序结果，并询问是否生成分析报告。

---

## 使用方法

### 典型工作流

```text
1. search 相场断裂                     # 搜索主题
2. 自动 AI 分析                         # 查看结构化报告
3. detail 3                             # 深入解读第 3 篇
4. detail 1 3 5                         # 多篇对比分析
5. ingest 3                             # 下载 PDF + 保存元数据到 wiki/
6. 将 wiki_bridge prompt 交给 LLM agent  # 完成双向链接知识库
7. ask 这个领域有哪些未解决的问题         # 自由提问
```

### 搜索深度

- **depth 1**（默认）：仅搜索原始论文
- **depth 2**：搜索原始论文 + 追踪其引用文献
- **depth 3+**：递归深入引用链

---

## 配置说明

所有配置在 `.env` 文件中：

```env
# 必填
DEEPSEEK_API_KEY=sk-your_key_here        # AI 分析和查询优化
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 可选 — 不填则自动跳过对应数据源
SCOPUS_API_KEY=your_scopus_key_here      # Elsevier Scopus API
PUBMED_API_KEY=your_pubmed_key_here      # PubMed（有 Key 可提速）

# 搜索设置
MAX_RESULTS_PER_SOURCE=10                # 每源最大结果数
```

### API Key 获取指南

| API | 是否必填 | 无限速 | 有限速 | 获取地址 |
|-----|---------|--------|--------|---------|
| DeepSeek | **是** | N/A | — | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| Scopus | 否 | N/A (跳过) | ~20次/秒 | [dev.elsevier.com](https://dev.elsevier.com/) |
| PubMed | 否 | 3次/秒 | 10次/秒 | [NCBI Settings](https://account.ncbi.nlm.nih.gov/settings/) |
| arXiv | 否 | 1次/30秒 | N/A (公开 API) | 无需申请 |
| CrossRef | 否 | 合理使用 | N/A (公开 API) | 无需申请 |

### 校园网/VPN 访问

- **在校内** — 直接访问出版商 PDF
- **校外** — 先连接校园 VPN，再运行工具
- **无 VPN** — arXiv 论文始终免费；其他论文会显示手动下载链接

---

## 命令参考

| 命令 | 说明 | 示例 |
|---------|-------------|---------|
| `search <主题>` | 搜索研究主题（中英文） | `search 固态电解质` |
| `depth <1-5>` | 设置搜索深度 | `depth 2` |
| `analyze` | AI 分析当前结果 | `analyze` |
| `detail <编号>` | 查看论文详情 + AI 解读 | `detail 3` |
| `detail 1 3 5` | 多篇对比分析（最多5篇） | `detail 1 3 5` |
| `ingest <编号>` | 下载 PDF + 保存元数据桩 | `ingest 3` |
| `ingest 1,3,5` | 批量摄入 | `ingest 1,3,5` |
| `ask <问题>` | 就当前主题自由提问 | `ask 有哪些开放问题` |
| `list` | 重新显示论文列表 | `list` |
| `guide` | 显示论文阅读方法框架 | `guide` |
| `help` | 显示所有命令 | `help` |
| `quit` | 退出程序 | `quit` |

---

## 进阶功能

### 深度搜索

设为 `depth 2` 或更高时，工具会递归追踪引用链：从搜索结果出发，通过 CrossRef API 获取每篇论文的参考文献列表，再去重获取新论文的详细信息。适用于：

- 找到领域的奠基文献
- 发现关键词搜索遗漏的相关工作
- 构建全面的文献综述

### PDF 自动下载

三阶段策略：

1. **Phase 1** — 直接 PDF 链接（arXiv 完全开放获取）
2. **Phase 2** — DOI → HTML 解析提取 PDF 链接（校园网/VPN 下自动通过 IP 认证，支持 Elsevier/MDPI/Springer/Wiley/ACS 等）
3. **Phase 3** — Unpaywall OA 查找免费合法版本
4. **Selenium 兜底** — 启动真实浏览器处理反爬严格的出版商网站

### Wiki 知识库集成

`ingest <N>` 下载 PDF 并在 `wiki/sources/literature/` 创建元数据桩，包含：

- YAML frontmatter（标题、作者、年份、期刊、DOI、标签）
- 完整摘要
- 待填写的笔记占位区（研究目标、方法、发现、对当前研究主题的价值）

`wiki_bridge.py` 采用两阶段设计，适合接入任何本地 Markdown/Obsidian 风格知识库：

1. **桥接阶段（自动、高确定性）**：`WikiBridge.ingest_paper(paper, topic)` 负责重复检测、生成文献页文件名、下载 PDF、写入元数据桩，并在 `wiki/log.md` 追加摄入记录。它不会读取 PDF 正文，也不会生成深度解读。
2. **知识库维护阶段（LLM agent）**：调用 `build_agent_prompt(pending, topic)` 获取待处理论文清单，让你的 LLM agent 按 `wiki/CLAUDE.md` 或自定义规范读取 PDF、补全文献笔记、维护实体/概念页、更新索引并检查双向链接。

默认目录结构如下，可通过 `SEARCH_PAPERS_WIKI_DIR` 指向任意 wiki 根目录：

```text
wiki/
├── CLAUDE.md                    # 可选：LLM agent 维护规范
├── raw/literature/              # 原始 PDF，只读保存
├── sources/literature/          # wiki_bridge 生成的文献元数据桩
├── entities/                    # 领域实体页，如材料、方法、数据集、机构
├── concepts/                    # 领域概念页，如机制、模型、任务、指标
├── synthesis/                   # 跨文献综合分析
├── explorations/                # 探索性问题和研究想法
├── index.md                     # 全局索引
└── log.md                       # 摄入和维护日志
```

本仓库已内置初始 `wiki/` 骨架，并在 `wiki/CLAUDE.md` 中保存固态电池多物理场耦合研究的 LLM 维护规范。`wiki/raw/` 下的原始 PDF 和科研资产默认不纳入 git，只把可复现的 Markdown 知识页面纳入版本控制。

推荐的 LLM agent 后处理流程：

1. 读取 PDF；综述类优先读全文或前 12 页，研究类优先读前 8-10 页；PDF 缺失时基于摘要和元数据处理。
2. 替换 source 页中的占位符，补充研究问题、方法/模型、关键发现、创新点、局限性和对当前主题的价值。
3. 在相关实体/概念页中加入该文献的回链，保持 `related:` / `sources:` 使用 `[[page-id]]` 格式。
4. 更新 `wiki/index.md` 的分类索引和文献计数。
5. 在 `wiki/log.md` 记录处理日期、涉及页面和核心发现。

后处理完成后建议检查：`[[link]]` 是否断链、frontmatter 中双括号是否成对、被引用页面是否有回链、同一页面名是否在多个目录重复。`raw/` 保存原始资料，默认只读；`sources/`、`entities/`、`concepts/` 等 Markdown 页面由人工或 LLM agent 维护。

---

## 常见问题

<details>
<summary><b>Q: 可以使用 DeepSeek 以外的模型吗？</b></summary>

可以。项目使用 OpenAI 兼容的客户端。修改 `.env` 中的 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL` 即可切换到 OpenAI、Qwen、Ollama 等兼容接口。
</details>

<details>
<summary><b>Q: 校外能用吗？</b></summary>

可以。PDF 下载需要以下条件之一：
- 连接校园 VPN（推荐）
- arXiv 预印本（始终免费）
- 通过提供的 DOI 链接手动下载
</details>

<details>
<summary><b>Q: 国内高校和海外高校都能用吗？</b></summary>

都能用。工具设计为通用工具，与学校无关。Scopus 等 Elsevier 服务可能需要校园网或 VPN。界面文本均为中文。
</details>

<details>
<summary><b>Q: arXiv 提示 429 错误（被限速）？</b></summary>

工具内置了 30 秒以上的请求间隔和指数退避重试。如果仍被限速，等几分钟再试。
</details>

<details>
<summary><b>Q: 如何添加更多搜索源？</b></summary>

在 `sources.py` 中创建继承 `SearchSource` 的新类，实现 `name` 和 `search()` 方法，然后在 `search_all_sources()` 中注册。
</details>

---

## 项目架构

```
search-papers/
├── app.py              # 主 CLI 应用（交互循环）
├── config.py           # 配置管理（.env 加载）
├── models.py           # Paper 数据模型
├── agent.py            # DeepSeek AI agent（查询优化、论文分析）
├── sources.py          # 搜索源（arXiv、CrossRef、Scopus、PubMed）
├── wiki_bridge.py      # PDF 下载 + 知识库桥接
├── visual_planner.py   # Mermaid 可视化流程图生成
├── ai_analyze.py       # Qwen 长文档分析工具
├── tools/
│   ├── create_ppt.py   # PPT 演示文稿生成
│   └── generate_ppt.py # PPT 生成辅助
├── wiki/               # 一体化 LLM 科研 Wiki
│   ├── CLAUDE.md       # LLM 维护规范
│   ├── raw/            # 原始 PDF/资产，默认不提交真实文件
│   ├── sources/        # 文献笔记与元数据桩
│   ├── entities/       # 领域实体
│   ├── concepts/       # 领域概念
│   ├── synthesis/      # 跨文献综合分析
│   └── explorations/   # 探索性问题和研究想法
├── assets/
│   └── search-papers-intro.html  # HTML 演示文稿
└── .env.example        # 配置模板
```

---

## 贡献

欢迎贡献！以下方向特别需要帮助：

- **新搜索源** — Semantic Scholar、Web of Science、IEEE Xplore、百度学术
- **多语言支持** — 更好的多语言查询处理
- **导出格式** — BibTeX、RIS、Zotero 集成
- **GUI** — Web 或桌面界面

提交大 PR 前请先开 issue 讨论方案。

---

## 相关项目

- [arxiv-sanity](https://github.com/karpathy/arxiv-sanity-lite) — Karpathy 的 arXiv 论文推荐
- [paperswithcode](https://paperswithcode.com/) — 带代码的 ML 论文
- [Semantic Scholar API](https://api.semanticscholar.org/) — 免费学术图谱 API
- [OpenAlex](https://openalex.org/) — 开放学术作品目录

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。

---

<p align="center">
  <sub>为全球研究者打造。支持各高校图书馆访问。</sub>
</p>
