# 固态电池多物理场耦合研究 Wiki 维护规范

## 项目概述

这是一个基于 LLM Wiki 方法论构建的个人科研知识库，专注于多物理场耦合固态电池领域，涵盖：

- 文献阅读与管理
- 实验数据整理
- 仿真结果归档
- 知识积累与发现

本仓库中的 `wiki/` 目录就是 Wiki 根目录。`wiki_bridge.py` 默认会把文献 PDF 保存到 `wiki/raw/literature/`，并把文献元数据桩写入 `wiki/sources/literature/`。

## 目录结构

```text
wiki/
├── CLAUDE.md                  # 本文件，LLM 维护规范
├── README.md                  # Wiki 使用说明
├── raw/                       # 原始资料，只读，永不修改
│   ├── literature/            # 文献 PDF
│   ├── experiments/           # 实验数据
│   ├── simulations/           # 仿真文件
│   └── assets/                # 图片、图表等资源
├── index.md                   # 全局索引
├── log.md                     # 操作日志
├── entities/                  # 实体页面
│   ├── materials/             # 材料实体，如 NCM、NMC811、NVP、LLZO、LiPON
│   ├── structures/            # 结构实体，如 cathode、anode、solid-electrolyte、interface
│   └── fields/                # 物理场/表征实体，如 mechanical-stress、temperature-field、EIS、SEM、XRD
├── concepts/                  # 概念页面
├── sources/                   # 文献摘要页
│   ├── TEMPLATE.md
│   └── literature/
├── synthesis/                 # 综合分析页
├── explorations/              # 探索性分析
└── tools/                     # 可选工具脚本
```

## 核心原则

- `raw/` 目录永远只读：LLM 可以读取其中内容，但不得修改、重命名或删除原始资料。
- `wiki/` 中的 Markdown 页面由 LLM 维护：创建、更新、合并、删除都需要遵守本规范。
- 每次交互都应增值：问答结果、对比表、公式解释和研究判断可沉淀为新页面。
- 保持跨引用：相关页面之间使用 Obsidian 风格 wiki 链接。

## 命名规范

- 页面文件名使用英文。
- 中文内容写在页面内部。
- 空格使用 `-` 替代。
- 实体页链接示例：`[[NMC811]]`、`[[Li7La3Zr2O12]]`。
- 概念页链接示例：`[[electro-chemo-mechanical-coupling]]`。

## Frontmatter 要求

所有页面类型都必须包含：

```yaml
---
title: 页面标题
type: entity | concept | source | synthesis | exploration
tags: [tag1, tag2]
created: 2026-05-30
updated: 2026-05-30
---
```

Source 页面额外字段：

```yaml
authors: [Author1, Author2]
year: 2024
journal: Journal Name
volume: 10
pages: 12345
doi: 10.xxxx/xxxx
related: [[paper-a]], [[paper-b]]
```

Entity、Concept、Synthesis、Exploration 页面额外字段：

```yaml
sources: [[paper-a]], [[paper-b]]
related: [[page-a]], [[page-b]]
```

关键规则：

- `related:` 和 `sources:` 必须使用 Obsidian 双括号格式：`[[A]], [[B]]`。
- 严禁把 `related:` 和 `sources:` 写成 YAML 数组格式：`[A, B]` 或 `["A", "B"]`，否则 Obsidian 图谱无法识别。
- `tags:` 使用 YAML 数组格式：`[tag1, tag2]`。
- `authors:` 使用 YAML 数组格式：`[Author1, Author2]`。

## 工作流程

### Ingest：摄入新文献

1. 将 PDF 放入 `raw/literature/`，或通过 Search Papers 的 `ingest <N>` 让 `wiki_bridge.py` 自动下载并生成元数据桩。
2. 告知 LLM 处理新文献，或把 `build_agent_prompt()` 的输出交给 LLM agent。
3. LLM 按以下流程维护 Wiki。

#### Step 1：判断文献类型并读取 PDF

- 检查标题、摘要、期刊是否含 `review`、`survey`、`progress`、`perspective`、`overview` 等关键词。
- 综述类文献：信息密度高，读取全文或至少前 12 页，提取方法分类、对比表、材料体系差异、未来方向等。
- 研究类文献：读取前 8-10 页，关注模型框架、关键发现、创新点。
- 从 PDF 原文提取具体数据、表格、公式和对比结构。

#### Step 2：创建或完善 source 摘要页

路径：`sources/literature/[paper-id].md`。

要求：

- 严格遵循 `sources/TEMPLATE.md` 的标准格式。
- 必须包含核心研究问题、模型框架、关键发现、创新点、对当前研究主题的价值、相关实体、相关概念。
- 禁止 AI 生成内联 wiki 链接轰炸，不要让每句话都塞入多个 `[[link]]`。
- wiki 链接仅放在「相关实体」「相关概念」段落及 frontmatter 的 `related:` 字段。
- 标签示例：`review`、`simulation`、`experimental`、`phase-field-fracture`。

#### Step 3：更新相关实体/概念页面

- 将新 source ID 添加到所有相关实体页的 `sources:` 或 `related:` 字段。
- 将新 source ID 添加到所有相关概念页的 `sources:` 或 `related:` 字段。
- 确保被引用页面有回链，形成双向链接。

#### Step 4：更新 `index.md`

- 在正确的分类表中添加新文献行。
- 根据页面类型更新 Entities、Concepts、Sources、Synthesis 或 Explorations 索引。

#### Step 5：更新 `log.md`

记录日期、操作类型、涉及页面和核心发现。

## Post-Ingest 自检清单

每次写入或修改 Wiki 文件后，必须执行以下自检：

- 断链检查：`[[link]]` 指向的页面是否存在。
- 括号完整性：frontmatter 中 `[[` 和 `]]` 数量是否相等。
- 双向链接：新 `sources` 链接到的 entity/concept 页面是否有回链。
- 格式一致性：所有 `related:` 和 `sources:` 字段使用 `[[...]], [[...]]` 格式，不得使用 YAML 数组格式。
- 重复文件检查：同一页面名不存在于多个目录。

## Query：查询

1. 提出研究问题。
2. LLM 搜索相关 Wiki 页面。
3. 综合回答，并按需要沉淀为：
   - 直接回答
   - `explorations/` 下的新分析页
   - 对比表、公式解释、机制图或研究假设

## Lint：健康检查

定期执行：

- 检查矛盾点。
- 标记过时信息。
- 找出孤立页面。
- 建议缺失链接。

## 特殊文件说明

### `index.md`

按类别组织所有页面索引：

- Entities：材料、电池组件、物理场、表征方法
- Concepts：理论、机制、模型、方法
- Sources：文献摘要
- Synthesis：跨文献综合分析
- Explorations：探索性研究问题

### `log.md`

时间线记录格式：

```text
[2026-05-30] ingest | Paper Title
[2026-05-30] query | 研究问题
[2026-05-30] lint | 健康检查报告
```

## 领域特定约定

实体类型：

- 材料：`[[NCM]]`、`[[NMC811]]`、`[[NVP]]`、`[[LLZO]]`、`[[LiPON]]`
- 电池结构：`[[cathode]]`、`[[anode]]`、`[[solid-electrolyte]]`、`[[interface]]`
- 物理场：`[[mechanical-stress]]`、`[[temperature-field]]`、`[[electric-field]]`、`[[concentration-field]]`
- 表征方法：`[[EIS]]`、`[[XRD]]`、`[[SEM]]`

概念类型：

- 耦合机制：电-化学-力学耦合
- 表征方法：EIS、XRD、SEM
- 仿真方法：FEM、DEM、多物理场耦合

标签系统：

- `material`
- `structure`
- `mechanism`
- `characterization`
- `simulation`
- `solid-electrolyte`
- `interface`
- `layer-design`

## 成功标准

- 新文献摄入后，相关页面在 1 次交互内更新。
- 任意实体/概念页面包含完整 inbound links。
- 能够回答“某材料在某电池结构中的电-力学耦合机制”类问题。
- 6 个月后 Wiki 页面数超过 100。
