"""
DeepSeek AI Agent - 负责查询优化、论文分析、综合报告
"""
import json
from typing import Optional

from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError

from config import Config
from models import Paper


class DeepSeekAgent:
    """使用 DeepSeek API 的 AI Agent"""

    def __init__(self, config: Config):
        self.client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            timeout=60.0,
            max_retries=1,
        )
        self.model = config.deepseek_model

    def _chat(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
        """统一的聊天调用"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except APITimeoutError:
            raise RuntimeError("DeepSeek API 超时（60s），请检查网络或稍后重试")
        except APIConnectionError:
            raise RuntimeError("无法连接 DeepSeek API，请检查网络或 base_url")
        except APIStatusError as e:
            if e.status_code == 401:
                raise RuntimeError("DeepSeek API Key 无效或已过期，请检查 .env 中的 DEEPSEEK_API_KEY")
            raise RuntimeError(f"DeepSeek API 错误 ({e.status_code}): {e.message}")

    # ── 1. 优化搜索查询 ──────────────────────────
    def optimize_query(self, user_topic: str) -> dict:
        """
        将用户描述的主题优化为学术搜索关键词。
        返回: {
            "english_query": "...",
            "chinese_query": "...",
            "search_terms": ["term1", "term2", ...],
            "suggested_filters": {"year_from": ..., "fields": [...]}
        }
        """
        system = """你是一个学术搜索优化专家。用户会描述一个研究主题，你需要：
1. 将中文主题转化为精准的英文搜索关键词
2. 提供中文搜索关键词
3. 列出 3-5 个核心搜索术语

重要：english_query 必须是 逗号分隔 的关键词格式，用于 arXiv API 精确匹配。
多词短语用英文引号包裹，如 "solid-state battery", "phase field", "crack propagation"。
不要写成自然语句，只写关键词。

只返回 JSON，不要其他文字。格式:
{
    "english_query": ""solid-state battery", "phase field fracture", "interfacial debonding"",
    "chinese_query": "中文关键词",
    "search_terms": ["term1", "term2", "term3"],
    "topic_summary": "简短的英文主题描述",
    "suggested_filters": {
        "year_from": null,
        "fields": []
    }
}"""
        result = self._chat(system, f"研究主题: {user_topic}")
        # 提取 JSON
        try:
            # 尝试从 markdown code block 中提取
            if "```" in result:
                json_str = result.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                return json.loads(json_str.strip())
            return json.loads(result)
        except (json.JSONDecodeError, IndexError):
            return {
                "english_query": user_topic,
                "chinese_query": user_topic,
                "search_terms": [user_topic],
                "topic_summary": user_topic,
                "suggested_filters": {},
            }

    # ── 2. 分析和排序论文 ────────────────────────
    def analyze_papers(self, topic: str, papers: list[Paper]) -> str:
        """对搜索到的论文进行分析、去重、排序和综述"""
        if not papers:
            return "未找到相关论文。请尝试调整搜索关键词。"

        papers_info = []
        for i, p in enumerate(papers, 1):
            star_str = "★" * p.stars + "☆" * (5 - p.stars) if p.stars > 0 else "未评分"
            venue_text = f"\n   期刊: {p.venue}" if p.venue else ""
            info = f"""[{i}] {p.title}  ({star_str})
   作者: {p.authors_str}{venue_text}
   年份: {p.year or '未知'}  |  来源: {p.source}  |  引用数: {p.citation_count or '未知'}
   期刊/会议: {p.venue or '未知'}
   摘要: {p.short_abstract(400)}
   URL: {p.url}
   DOI: {p.doi or '无'}"""
            papers_info.append(info)

        papers_text = "\n\n".join(papers_info)

        system = """你是一个资深的学术研究助手。你需要对搜索到的论文进行分析，生成一份结构化的研究报告。

要求:
1. **去重**: 如果同一篇论文出现在多个搜索源中，合并为一条
2. **相关性排序**: 按与研究主题的相关性对论文排序
3. **分类归纳**: 将论文按子主题/研究方向分组
4. **综述摘要**: 写一段简短的领域综述
5. **推荐**: 标注最值得阅读的论文（Top 5）
6. **研究趋势**: 总结该领域的研究趋势

输出格式要求（使用 Markdown）:

【重要 - 编号规则】论文列表中的每篇论文都有编号 [N]。在报告中引用任何论文时，必须带上其原始编号 [N]！这样用户可以用 detail N 命令查看该论文的详细解读。

## 📊 搜索结果综述
简短的领域概述...

## 🏆 推荐论文 Top 5
按推荐程度排序，每篇必须包含:
- **[N] 英文标题** / 中文翻译
  - 作者: ... | 期刊: ... | 年份: ... | 引用: ... | 推荐理由 | [链接]

## 📁 分类论文列表
### 子方向1（中文名）
- **[N] 英文标题** / 中文翻译
  - 作者: ... | 期刊: ... | 年份: ... | 引用: ... | [链接]
### 子方向2（中文名）
- **[N] 英文标题** / 中文翻译
  - 作者: ... | 期刊: ... | 年份: ... | 引用: ... | [链接]

## 📈 研究趋势
趋势分析...

## 💡 进一步研究建议
建议...
"""

        user_msg = f"""研究主题: {topic}

以下是从多个学术数据库搜索到的论文:

{papers_text}

请分析这些论文并生成研究报告。"""

        return self._chat(system, user_msg, temperature=0.4, max_tokens=16384)

    # ── 3. 深入解读单篇论文 ─────────────────────
    def explain_paper(self, paper: Paper) -> str:
        """深入解读一篇论文"""
        system = """你是一位学术论文解读专家。请根据提供的论文信息（标题、摘要等），给出:
1. **论文核心贡献**: 一句话总结
2. **方法论**: 使用了什么方法/技术
3. **关键发现**: 主要结论
4. **适合读者**: 这篇论文适合什么背景的读者
5. **相关工作**: 可能的相关研究方向

使用中文回答。"""

        user_msg = f"""标题: {paper.title}
作者: {paper.authors_str}
年份: {paper.year}
期刊/会议: {paper.venue}
摘要: {paper.abstract}
链接: {paper.url}"""

        base_result = self._chat(system, user_msg, temperature=0.3)

        # 生成针对本文的专属阅读指南
        guide_system = """你是一位学术论文阅读指导专家。用户会提供一篇论文的标题、作者、年份、期刊和摘要。
请根据这些信息，生成一份**针对本文的专属阅读指南**，区别于通用模板。

格式要求（全部使用中文，按顺序回答）:

1. **本文填补的研究空白** — 前人没做什么，本文做了什么
2. **推荐阅读顺序** — 建议先读哪个部分（摘要/引言/方法/实验/讨论）及原因
3. **核心图表** — 建议先看哪张图或哪个实验，它最能体现本文价值
4. **潜在局限性** — 基于领域知识指出本文可能的不足（1-2条即可）
5. **一句话标签** — 格式: `[年份]作者_一句话核心结论_缺陷`，如: `[2023]Zhang_通过XX方法首次实现YY_未在真实场景验证`
6. **找同类文献** — 输入什么关键词/DOI可以找到本文的祖师爷（奠基工作）和后浪（后续改进/应用）"""

        guide_user = f"""论文标题: {paper.title}
作者: {paper.authors_str}
年份: {paper.year}
期刊/会议: {paper.venue}
摘要: {paper.abstract}"""

        guide_result = self._chat(guide_system, guide_user, temperature=0.3)

        return f"{base_result}\n\n---\n\n## 🎯 针对本文的专属阅读指南\n\n{guide_result}"

    # ── 3a2. AI 生成科研机理图 ────────────────────
    def explain_visual(self, paper: Paper) -> dict:
        """
        从论文摘要提取专属科研节点，生成简洁 Mermaid 流程图。
        返回 {"visual_type": "...", "mermaid": "..."}
        """
        system = """你是一个科研流程图生成器。阅读论文摘要，提取 4-6 个本文专属的关键步骤，生成极简 Mermaid flowchart。

规则：
1. 先判断论文类型：实验研究 / 数值仿真 / 理论推导 / AI驱动 / 综述 / 机理分析
2. 从摘要中提取 4-6 个本文专属的步骤或发现，每个节点用中文描述（<=12字）
3. 节点必须使用论文中实际出现的方法、材料、发现，严禁泛词（如 "步骤1"、"实验"）
4. 图只用最简格式：flowchart LR 或 flowchart TB，节点用 N0,N1... , 用 --> 连接

示例一（实验类 LAGP 晶界论文）：
标题: Grain boundary phase engineering in LAGP...
摘要: ...SPS sintering at 650-750C, 3D FIB-SEM, MAS NMR, DFT, Li4P2O7 and Li9Al3 phase...
→
{"visual_type":"实验研究","mermaid":"flowchart LR\n  N0[SPS烧结650-750C]\n  N1[3D FIB-SEM重建形貌]\n  N2[MAS NMR+DFT解析相组成]\n  N3[Li9Al3无序相主导晶界]\n  N4[离子电导率最优]\n  N0 --> N1 --> N2\n  N2 --> N3\n  N3 --> N4"}

示例二（仿真类相场断裂论文）：
标题: Phase-field modeling of fracture in...
摘要: ...phase-field, crack propagation, FEM, energy minimization...
→
{"visual_type":"数值仿真","mermaid":"flowchart TB\n  N0[相场断裂模型]\n  N1[有限元离散]\n  N2[能量极小化求解]\n  N3[裂纹扩展路径]\n  N4[与实验对比验证]\n  N0 --> N1 --> N2 --> N3 --> N4"}

示例三（综述类）：
→
{"visual_type":"综述","mermaid":"flowchart LR\n  N0[固态电解质分类]\n  N1[界面失效机制]\n  N2[表征方法对比]\n  N3[改性策略总结]\n  N4[未来研究方向]\n  N0 --> N1 --> N2 --> N3 --> N4"}

只返回 JSON。visual_type 取值: 实验研究 / 数值仿真 / 理论推导 / AI驱动 / 综述 / 机理分析"""

        user = f"""标题: {paper.title}
摘要: {paper.abstract[:2000] if paper.abstract else '无'}"""

        try:
            result = self._chat(system, user, temperature=0.3, max_tokens=1024)
            if "```" in result:
                json_str = result.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                return json.loads(json_str.strip())
            return json.loads(result)
        except Exception:
            pass

        return {"visual_type": "", "mermaid": ""}

    # ── 3b. 多篇论文对比分析 ─────────────────────
    def compare_papers(self, papers: list[Paper], topic: str) -> str:
        """对多篇论文（2-5篇）进行关联分析"""
        papers_info = []
        for i, p in enumerate(papers, 1):
            papers_info.append(f"""[{i}] {p.title}
   作者: {p.authors_str}
   年份: {p.year or '未知'}
   期刊: {p.venue or '未知'}
   摘要: {p.short_abstract(500)}""")
        papers_text = "\n\n".join(papers_info)

        system = """你是一位学术研究顾问。用户同时阅读了多篇论文，需要你分析它们之间的关联。

请从以下角度进行分析（使用中文）:

1. **共同主线** — 这几篇论文围绕什么核心问题？有什么共同的学术脉络？
2. **互补关系** — 它们在方法、发现、应用上如何互补？A 的不足是否被 B 填补？
3. **矛盾/差异** — 是否存在不一致的结论或方法论分歧？
4. **完整图景** — 综合这些论文，你能勾勒出该方向的什么完整图景？
5. **阅读顺序建议** — 建议按什么顺序深入阅读，理由是什么？

使用 Markdown 格式输出，简洁有料。"""

        user_msg = f"""研究主题: {topic}

以下是我同时阅读的 {len(papers)} 篇论文:

{papers_text}

请分析它们之间的关联。"""

        return self._chat(system, user_msg, temperature=0.4, max_tokens=4096)

    # ── 3c. 批量翻译论文标题 ─────────────────────
    def translate_paper_titles(self, papers: list[Paper]) -> dict[int, str]:
        """批量将论文标题翻译为中文，返回 {paper_index: chinese_title}"""
        if not papers:
            return {}

        papers_text = "\n".join(
            f"[{i}] {p.title}" for i, p in enumerate(papers)
        )

        system = """你是一位学术翻译专家。请将以下英文论文标题翻译为中文。
要求:
- 翻译准确、流畅，符合中文学术表达习惯
- 保留原意，可适当精简
- 只返回翻译结果，每行一个，格式: "[序号] 中文标题"

只输出翻译结果，不要其他说明。"""

        result = self._chat(system, f"待翻译标题:\n{papers_text}", temperature=0.3)

        translations = {}
        for line in result.splitlines():
            line = line.strip()
            if not line:
                continue
            # 匹配 ["[1] 标题"] 或 "[1] 标题" 格式
            m = re.match(r"^\[(\d+)\]\s*(.+)$", line)
            if m:
                idx = int(m.group(1))
                translations[idx] = m.group(2).strip()
        return translations

    # ── 4. 生成文档标题 ────────────────────────────
    def generate_doc_title(self, user_topic: str) -> str:
        """根据用户输入的搜索主题，用 AI 生成一个简洁的文档标题"""
        system = """你是一个学术文档命名专家。用户会给你一个研究搜索主题，你需要生成一个简洁、专业的中文文档标题。
要求:
- 标题简洁，10-25 个字以内
- 能准确反映研究主题
- 适合作为文件名和文档标题
- 只返回标题文本，不要引号、不要其他说明"""

        result = self._chat(system, f"搜索主题: {user_topic}", temperature=0.3)
        # 清理标题，移除不合法的文件名字符
        title = result.strip().strip('"\'《》')
        return title

    # ── 5. 自由问答 ──────────────────────────────
    def ask_about_topic(self, topic: str, papers: list[Paper], question: str) -> str:
        """关于论文或主题的自由问答"""
        papers_context = "\n".join(
            f"- [{p.title}] ({p.year}, {p.authors_str}): {p.short_abstract(200)}"
            for p in papers[:15]
        )

        system = """你是一个学术研究助手，拥有丰富的跨学科知识。
用户正在研究一个特定主题，并已搜索到一些相关论文。
请根据论文信息和你的知识回答用户的问题。
回答要准确、专业，使用中文。"""

        user_msg = f"""研究主题: {topic}

已搜索到的论文:
{papers_context}

用户问题: {question}"""

        return self._chat(system, user_msg, temperature=0.4)
