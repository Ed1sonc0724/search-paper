"""
Search Papers - AI 学术论文搜索助手
交互式命令行界面
"""
import asyncio
import sys
import os
import re
import time

# Rich 终端美化
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from config import Config
from models import Paper
from agent import DeepSeekAgent
from sources import search_all_sources, deep_search, backfill_citations, compute_star_ratings
from wiki_bridge import WikiBridge

console = Console(record=True)



# ─────────────────────────────────────────────
#  阅读指南内容
# ─────────────────────────────────────────────
READING_GUIDE = """
## 📖 论文阅读指南（10秒定去留，5分钟抓骨架）

---

### 一、筛选与阅读

| 步骤 | 动作 | 核心任务 |
| :--- | :--- | :--- |
| **1. 扫标题/摘要** | 只看最后一句话 | 判断 **值不值得读** |
| **2. 看图表** | 翻一遍大图及题注 | 不看正文先猜结论 |
| **3. 锁段落** | 引言末段 + 讨论首段 | 找 **"前人没做啥"** 与 **"我们做成了啥"** |
| **4. 记一句** | 在文件名后加标签 | 格式：`[年份]作者_一句话结论_缺陷` |

---

### 二、创新点提炼公式（替换摘要背诵）

> **前人对标物** → **改动的单一变量** → **反常规的数据结果**

- **动手写**：不同于 `___`(旧方法)`___` ，本文通过 `___`(只动一处)`___` ，**首次**实现了 `___`(意想不到的效果)`___`。
- **防忽悠**：见到 `First` 先打问号；见到 `Synergistic` 先问"1+1>2了吗"。

---

### 三、垂直文献获取（不搜关键词，顺藤摸瓜）

| 目的 | 操作方法 | 收获 |
| :--- | :--- | :--- |
| **找祖师爷** | 翻当前文章的 **References** | 领域奠基文献 |
| **找后浪** | Google Scholar 点 **Cited by** | 最新修正/批评/应用 |
| **找血亲** | **Connected Papers** 输入DOI | 同流派隐藏必读文献 |
"""


# ─────────────────────────────────────────────
#  UI 工具函数
# ─────────────────────────────────────────────
def print_banner():
    banner = """
 ╔══════════════════════════════════════════════════════╗
 ║       🔬 Search Papers - AI 学术论文搜索助手        ║
 ║                                                      ║
 ║   集成: arXiv · CrossRef · Scopus · PubMed           ║
 ║   AI:   DeepSeek 智能分析                            ║
 ╚══════════════════════════════════════════════════════╝
"""
    console.print(banner, style="bold cyan")


def print_papers_table(papers: list[Paper], title: str = "搜索结果", show_depth: bool = False):
    """以表格形式展示论文列表"""
    table = Table(title=title, box=box.ROUNDED, show_lines=True, expand=True)
    table.add_column("#", style="bold yellow", width=3)
    if show_depth:
        table.add_column("深度", style="yellow", width=4)
    table.add_column("推荐", style="bold yellow", width=6)
    table.add_column("标题", style="bold white", ratio=3)
    table.add_column("作者", style="cyan", ratio=2)
    table.add_column("年份", style="green", width=6)
    table.add_column("引用", style="magenta", width=6)
    table.add_column("来源", style="blue", width=10)

    for i, paper in enumerate(papers, 1):
        # Stars display
        if paper.stars > 0:
            star_str = "★" * paper.stars + "☆" * (5 - paper.stars)
        else:
            star_str = "[dim]—————[/dim]"

        # Year display
        year_str = str(paper.year) if paper.year else "[dim]??[/dim]"

        # Citation display
        if paper.citation_count is not None:
            cite_str = str(paper.citation_count)
        else:
            cite_str = "[dim]N/A[/dim]"

        row = [str(i)]
        if show_depth:
            row.append(str(paper.depth) if paper.depth else "-")
        row.extend([
            star_str,
            paper.title[:75] + ("..." if len(paper.title) > 75 else ""),
            paper.authors_str,
            year_str,
            cite_str,
            paper.source,
        ])
        table.add_row(*row)
    console.print(table)


def print_paper_detail(paper: Paper, index: int):
    """打印单篇论文详情"""
    ga_line = f"[bold]图形摘要:[/bold] {paper.graphical_abstract}" if paper.graphical_abstract else "[dim]图形摘要:[/dim] 无"
    star_str = "★" * paper.stars + "☆" * (5 - paper.stars) if paper.stars > 0 else "未评分"
    relevance_str = f" (相关性: {paper.relevance_score:.0%})" if paper.relevance_score > 0 else ""
    venue_line = f"\n[yellow]期刊:[/yellow] {paper.venue}" if paper.venue else ""
    detail = f"""[bold yellow]#{index}[/bold yellow] [bold]{paper.title}[/bold]

[yellow]推荐指数:[/yellow] {star_str}{relevance_str}
[cyan]作者:[/cyan] {paper.authors_str}{venue_line}
[green]年份:[/green] {paper.year or '未知'}
[magenta]引用数:[/magenta] {paper.citation_count if paper.citation_count is not None else '未知'}
[blue]来源:[/blue] {paper.source}
[yellow]期刊/会议:[/yellow] {paper.venue or '未知'}
[red]DOI:[/red] {paper.doi or '无'}

[bold]链接:[/bold] {paper.url}
[bold]PDF:[/bold] {paper.pdf_url or '无'}
{ga_line}

[bold]摘要:[/bold]
{paper.abstract[:500]}{'...' if len(paper.abstract) > 500 else ''}
"""
    console.print(Panel(detail, title="论文详情", border_style="green"))


# ─────────────────────────────────────────────
#  核心搜索流程
# ─────────────────────────────────────────────
class PaperSearchApp:
    def __init__(self):
        self.config = Config.from_env()
        self.agent: DeepSeekAgent = None
        self.wiki: WikiBridge = None
        self.current_papers: list[Paper] = []
        self.current_topic: str = ""
        self.last_report: str = ""  # 最近一次 AI 分析报告
        self.search_depth: int = 1   # 搜索深度（1=只搜第一层, 2=追踪引用, ...）

    def initialize(self) -> bool:
        """初始化应用"""
        errors = self.config.validate()
        if errors:
            for err in errors:
                console.print(f"[red]❌ {err}[/red]")
            console.print("\n[yellow]请复制 .env.example 为 .env 并填入你的 API Key[/yellow]")
            return False
        self.agent = DeepSeekAgent(self.config)
        self.wiki = WikiBridge(self.agent)
        return True

    async def search_topic(self, topic: str, depth: int = None) -> list[Paper]:
        """搜索主题，支持指定搜索深度"""
        self.current_topic = topic
        search_depth = depth if depth is not None else self.search_depth

        # Step 1: AI 优化查询
        console.print("\n[bold blue]🤖 AI 正在优化搜索查询...[/bold blue]")
        with console.status("[bold green]思考中...", spinner="dots"):
            optimized = self.agent.optimize_query(topic)

        eng_query = optimized.get("english_query", topic)
        search_terms = optimized.get("search_terms", [topic])
        topic_summary = optimized.get("topic_summary", topic)

        console.print(f"  [green]✓[/green] 英文查询: [bold]{eng_query}[/bold]")
        console.print(f"  [green]✓[/green] 核心术语: {', '.join(search_terms)}")
        if search_depth > 1:
            console.print(f"  [green]✓[/green] 搜索深度: [bold]{search_depth}[/bold] （将递归追踪引用文献）")

        # Step 2: 多源搜索（支持深度）
        console.print("\n[bold blue]🔍 正在搜索多个学术数据库...[/bold blue]")

        def on_depth_start(current_d, total_d):
            if current_d == 1:
                console.print(f"  [cyan]📖 第 {current_d}/{total_d} 层: 搜索原始论文...[/cyan]")
            else:
                console.print(f"  [cyan]🔗 第 {current_d}/{total_d} 层: 检索引用文献...[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("搜索中...", total=None)
            results = await deep_search(
                eng_query, self.config,
                depth=search_depth,
                on_depth_start=on_depth_start,
            )
            progress.update(task, description="搜索完成!")

        # 汇总结果 — 确保四个源全部列出
        all_papers = []
        expected = ["arXiv", "CrossRef", "Scopus", "PubMed"]
        for src in expected:
            papers = results.get(src, [])
            console.print(f"  [green]✓[/green] {src}: 找到 {len(papers)} 篇论文")
            all_papers.extend(papers)
        # 如果还有不在 expected 列表中的源也一起汇总
        for source_name, papers in results.items():
            if source_name not in expected:
                console.print(f"  [green]✓[/green] {source_name}: 找到 {len(papers)} 篇论文")
                all_papers.extend(papers)

        if not all_papers:
            console.print("[red]未找到任何论文。请尝试其他关键词。[/red]")
            return []

        # 补充 arXiv 论文的引用数据 + 计算推荐指数
        if all_papers:
            with console.status("[bold green]📊 计算推荐指数...", spinner="dots"):
                await backfill_citations(all_papers)
                compute_star_ratings(all_papers, topic, search_terms)

        self.current_papers = all_papers

        # 显示论文表格（深度>1时显示深度列）
        has_deep = any(p.depth > 1 for p in all_papers)
        print_papers_table(all_papers, f"搜索结果 - {topic}", show_depth=has_deep)

        return all_papers

    def analyze_results(self):
        """AI 分析搜索结果"""
        if not self.current_papers:
            console.print("[red]请先执行搜索。[/red]")
            return

        console.print("\n[bold blue]🤖 AI 正在分析论文...[/bold blue]")
        with console.status("[bold green]深度分析中（可能需要 10-30 秒）...", spinner="dots"):
            report = self.agent.analyze_papers(self.current_topic, self.current_papers)

        console.print()
        console.print(Panel(Markdown(report), title="📊 AI 分析报告", border_style="cyan", expand=True))
        self.last_report = report
        return report

    def explain_single_paper(self, index: int):
        """解读单篇论文"""
        if index < 1 or index > len(self.current_papers):
            console.print(f"[red]无效编号。请输入 1-{len(self.current_papers)}[/red]")
            return

        paper = self.current_papers[index - 1]
        print_paper_detail(paper, index)

        console.print("\n[bold blue]🤖 AI 深度解读中...[/bold blue]")
        with console.status("[bold green]分析中...", spinner="dots"):
            explanation = self.agent.explain_paper(paper)

        console.print()
        console.print(Panel(Markdown(explanation), title="🔍 AI 论文解读", border_style="yellow"))

        # GA（图形摘要）处理
        self._handle_graphical_abstract(paper)

        # 显示通用阅读指南模板（专属指南已集成在上方 AI 解读中）
        console.print()
        console.print("[dim]💡 通用阅读模板: 输入 [yellow]guide[/yellow] 可查看 10秒定去留/5分钟抓骨架 的阅读框架[/dim]")

    def _handle_graphical_abstract(self, paper: Paper):
        """询问并下载/查看图形摘要（轻量实现，不依赖 PIL）"""
        if not paper.graphical_abstract:
            return

        console.print()
        console.print(f"[bold]🖼 图形摘要:[/bold] [link]{paper.graphical_abstract}[/link]")

        do_fetch = Confirm.ask("是否下载图形摘要到本地？", default=False)
        if not do_fetch:
            return

        import urllib.request
        import os

        save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ga_images")
        os.makedirs(save_dir, exist_ok=True)

        # 从 URL 推断扩展名
        ga_url = paper.graphical_abstract
        ext = os.path.splitext(ga_url.split("?")[0])[1]
        if not ext or len(ext) > 5:
            ext = ".gif"  # CrossRef 图形摘要因常为 GIF
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in paper.title)[:50]
        filepath = os.path.join(save_dir, f"ga_{safe_title}{ext}")

        try:
            urllib.request.urlretrieve(ga_url, filepath)
            console.print(f"[green]✓ 已保存到: {filepath}[/green]")
        except Exception as e:
            console.print(f"[red]下载失败: {e}[/red]")
            console.print(f"[dim]可手动复制链接下载: {ga_url}[/dim]")

    def ingest_single(self, index: int):
        """摄入单篇论文：下载 PDF + 写元数据桩"""
        if index < 1 or index > len(self.current_papers):
            console.print(f"[red]无效编号。请输入 1-{len(self.current_papers)}[/red]")
            return

        paper = self.current_papers[index - 1]
        console.print(f"\n[bold]📥 正在处理:[/bold] {paper.title[:80]}...")

        # 预检重复
        if self.wiki.has_duplicate(paper):
            console.print(f"[yellow]⚠ 该论文可能已存在于 wiki 中，跳过。[/yellow]")
            return

        with console.status("[bold green]下载 PDF + 写入元数据桩...", spinner="dots"):
            result = self.wiki.ingest_paper(paper, self.current_topic)

        if result["status"] == "created":
            pdf_name = result.get("pdf")
            pdf_status = f"[green]已下载[/green]" if pdf_name else "[yellow]未下载[/yellow]"
            console.print(f"[green]✅ 元数据桩已写入: {result['path']}[/green]")
            console.print(f"   PDF: {pdf_status}")
            if not pdf_name:
                doi = result.get("paper", {}).get("doi", "")
                url = result.get("paper", {}).get("url", "")
                if doi:
                    console.print(f"   [cyan]🔗 手动下载: https://doi.org/{doi}[/cyan]")
                elif url:
                    console.print(f"   [cyan]🔗 手动下载: {url}[/cyan]")
            if result.get("pdf_diag"):
                for line in result["pdf_diag"][-2:]:  # 只显示最后 2 条关键诊断
                    console.print(f"     [dim]{line}[/dim]")
            console.print(f"[dim]💡 Wiki agent 尚未处理此论文。使用 wiki CLI 启动 agent 完成 CLAUDE.md 工作流。[/dim]")
        elif result["status"] == "skipped":
            console.print(f"[yellow]⏭ 跳过: {result['reason']}[/yellow]")
        else:
            console.print(f"[red]❌ 错误: {result.get('reason', '未知错误')}[/red]")

    def ingest_selected(self, indices: list[int]):
        """批量摄入选中的论文"""
        results = []
        for idx in indices:
            if idx < 1 or idx > len(self.current_papers):
                console.print(f"[red]无效编号 {idx}，跳过[/red]")
                continue
            paper = self.current_papers[idx - 1]
            if self.wiki.has_duplicate(paper):
                console.print(f"[yellow]⏭ #{idx} 已存在，跳过: {paper.title[:60]}...[/yellow]")
                continue
            with console.status(f"[bold green]#{idx} 下载 PDF + 写元数据桩...", spinner="dots"):
                result = self.wiki.ingest_paper(paper, self.current_topic)
            results.append((idx, paper, result))

        created = sum(1 for _, _, r in results if r["status"] == "created")
        skipped = sum(1 for _, _, r in results if r["status"] == "skipped")
        pdf_ok = sum(1 for _, _, r in results if r.get("pdf"))
        pdf_failed = created - pdf_ok
        console.print(f"\n[bold]📊 处理结果:[/bold] [green]{created} 新建[/green] / [yellow]{skipped} 跳过[/yellow] | PDF: [green]{pdf_ok}[/green]/[yellow]{pdf_failed}[/yellow]")
        for idx, paper, r in results:
            status = "✅" if r["status"] == "created" else "⏭"
            pdf_tag = " [PDF]" if r.get("pdf") else ""
            console.print(f"  {status} #{idx}: {paper.title[:70]}...{pdf_tag}")
            if not r.get("pdf") and paper.doi:
                console.print(f"       [cyan]🔗 https://doi.org/{paper.doi}[/cyan]")
        if created > 0:
            console.print(f"[dim]💡 Wiki agent 尚未处理以上论文，元数据桩已就绪。[/dim]")

    def ask_question(self, question: str):
        """关于当前主题的问答"""
        console.print("\n[bold blue]🤖 AI 思考中...[/bold blue]")
        with console.status("[bold green]生成回答...", spinner="dots"):
            answer = self.agent.ask_about_topic(
                self.current_topic, self.current_papers, question
            )
        console.print()
        console.print(Panel(Markdown(answer), title="💬 AI 回答", border_style="green"))

    async def related_search(self, indices: list[int] = None):
        """功能已移除"""
        console.print("[yellow]引用文献搜索功能已移除。[/yellow]")

    def show_reading_guide(self):
        """显示论文阅读指南"""
        console.print(Panel(
            Markdown(READING_GUIDE),
            title="📖 论文阅读指南",
            border_style="cyan",
            expand=False,
        ))


# ─────────────────────────────────────────────
#  主循环
# ─────────────────────────────────────────────
def print_help():
    help_text = """
[bold]可用命令:[/bold]
  [yellow]search <主题>[/yellow]  - 搜索新的研究主题
  [yellow]depth <数字>[/yellow]   - 设置搜索深度（默认1，范围1-5，越深追踪越多引用）
  [yellow]analyze[/yellow]        - AI 分析当前搜索结果
  [yellow]detail <编号>[/yellow]  - 查看论文详情（支持空格多选，如 detail 1 3 5，最多5篇，多篇会做关联分析）
  [yellow]ingest <编号>[/yellow]  - 下载 PDF + 写元数据桩（wiki agent 另行处理）
  [yellow]guide[/yellow]          - 显示论文阅读指南
  [yellow]ask <问题>[/yellow]     - 就当前主题向 AI 提问
  [yellow]list[/yellow]           - 重新显示论文列表
  [yellow]help[/yellow]           - 显示帮助
  [yellow]quit[/yellow]           - 退出
"""
    console.print(Panel(help_text, title="帮助", border_style="blue"))


def _parse_detail_indices(arg: str, max_n: int = 100) -> list[int]:
    """解析空格分隔的论文编号，最多 5 个，去重排序"""
    if not arg:
        return []
    indices = []
    for part in arg.split():
        if part.isdigit():
            n = int(part)
            if 1 <= n <= max_n and n not in indices:
                indices.append(n)
                if len(indices) >= 5:
                    break
    return sorted(indices)


def _parse_indices(arg: str, max_n: int) -> list[int]:
    """解析 '1,3,5' 或 '1-3' 格式的索引字符串"""
    indices = []
    for part in arg.split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                indices.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        elif part.isdigit():
            indices.append(int(part))
    return [i for i in indices if 1 <= i <= max_n]


async def main():
    print_banner()

    app = PaperSearchApp()
    if not app.initialize():
        sys.exit(1)

    console.print("[green]✓ 初始化成功！DeepSeek AI 已就绪。[/green]\n")
    print_help()

    # 如果命令行带了参数，直接搜索
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
        await app.search_topic(topic)
        app.analyze_results()

    while True:
        try:
            console.print()
            depth_hint = f" (深度:{app.search_depth})" if app.search_depth > 1 else ""
            user_input = Prompt.ask(f"[bold cyan]📎 输入命令{depth_hint}[/bold cyan]").strip()
            if not user_input:
                continue

            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("quit", "exit", "q"):
                console.print("[yellow]👋 再见！[/yellow]")
                break

            elif cmd == "help":
                print_help()

            elif cmd == "search":
                if not arg:
                    arg = Prompt.ask("请输入研究主题")
                await app.search_topic(arg)
                # 自动进行分析
                if app.current_papers:
                    do_analyze = Confirm.ask("是否让 AI 分析这些论文？", default=True)
                    if do_analyze:
                        app.analyze_results()

            elif cmd == "analyze":
                app.analyze_results()

            elif cmd in ("detail", "view", "read"):
                # 支持单篇或多篇（空格分隔，最多5篇）
                indices = _parse_detail_indices(arg)
                if not indices:
                    arg = Prompt.ask("请输入论文编号（空格分隔可输入多篇，最多5篇）")
                    indices = _parse_detail_indices(arg)

                if len(indices) == 1:
                    # 单篇：原有流程
                    idx = indices[0]
                    app.explain_single_paper(idx)
                    # 询问是否下载 PDF + 写入元数据桩
                    if app.current_papers:
                        paper = app.current_papers[idx - 1]
                        dup_info = " [yellow](已存在)[/yellow]" if app.wiki.has_duplicate(paper) else ""
                        do_ingest = Confirm.ask(
                            f"[bold cyan]📥 下载 PDF 并写入元数据桩？{dup_info}[/bold cyan]",
                            default=False,
                        )
                        if do_ingest:
                            with console.status("[bold green]下载 PDF + 写入元数据桩...", spinner="dots"):
                                result = app.wiki.ingest_paper(paper, app.current_topic)
                            if result["status"] == "created":
                                pdf_name = result.get("pdf")
                                pdf_status = f"[green]已下载[/green]" if pdf_name else "[yellow]未下载[/yellow]"
                                console.print(f"[green]✅ 元数据桩: {result['path']}[/green] (PDF: {pdf_status})")
                                if not pdf_name:
                                    doi = result.get("paper", {}).get("doi", "")
                                    url = result.get("paper", {}).get("url", "")
                                    if doi:
                                        console.print(f"  [cyan]🔗 手动下载: https://doi.org/{doi}[/cyan]")
                                    elif url:
                                        console.print(f"  [cyan]🔗 手动下载: {url}[/cyan]")
                                console.print(f"[dim]💡 Wiki agent 待处理，使用 wiki CLI 启动。[/dim]")
                            elif result["status"] == "skipped":
                                console.print(f"[yellow]⏭ 跳过: {result['reason']}[/yellow]")

                elif len(indices) >= 2:
                    # 多篇：逐个展示详情 + 关联分析
                    selected = [app.current_papers[i - 1] for i in indices]
                    for idx in indices:
                        console.print()
                        console.print(f"[dim]━━━ 论文 #{idx} ━━━[/dim]")
                        app.explain_single_paper(idx)

                    # 关联分析
                    console.print()
                    console.print(f"[bold blue]🔗 AI 正在分析 {len(indices)} 篇论文的关联...[/bold blue]")
                    with console.status("[bold green]交叉分析中...", spinner="dots"):
                        comparison = app.agent.compare_papers(selected, app.current_topic)
                    console.print()
                    console.print(Panel(Markdown(comparison), title="🔗 论文关联分析", border_style="magenta"))

            elif cmd == "ask":
                if not arg:
                    arg = Prompt.ask("请输入你的问题")
                app.ask_question(arg)

            elif cmd == "guide":
                app.show_reading_guide()

            elif cmd == "depth":
                if arg and arg.isdigit():
                    n = int(arg)
                    if 1 <= n <= 5:
                        app.search_depth = n
                        console.print(f"[green]✓ 搜索深度已设置为 {n}[/green]")
                        if n == 1:
                            console.print("[dim]  只搜索第一层论文[/dim]")
                        else:
                            console.print(f"[dim]  将递归追踪到第 {n} 层引用文献[/dim]")
                    else:
                        console.print("[red]搜索深度请设置在 1-5 之间[/red]")
                else:
                    console.print(f"[cyan]当前搜索深度: {app.search_depth}[/cyan]")
                    console.print("[dim]使用 'depth <数字>' 设置，范围 1-5[/dim]")
                    console.print("[dim]  1 = 只搜索第一层论文[/dim]")
                    console.print("[dim]  2 = 搜索第一层 + 提取引用文献[/dim]")
                    console.print("[dim]  3+ = 继续深入追踪引用链[/dim]")

            elif cmd == "list":
                if app.current_papers:
                    has_deep = any(p.depth > 1 for p in app.current_papers)
                    print_papers_table(app.current_papers, f"搜索结果 - {app.current_topic}", show_depth=has_deep)
                else:
                    console.print("[yellow]暂无搜索结果[/yellow]")

            elif cmd == "ingest":
                if not arg:
                    console.print("[yellow]用法: ingest <编号>  如: ingest 3[/yellow]")
                elif arg.isdigit():
                    app.ingest_single(int(arg))
                else:
                    # 尝试解析如 "1,3,5" 或 "1-3"
                    indices = _parse_indices(arg, len(app.current_papers))
                    if indices:
                        app.ingest_selected(indices)
                    else:
                        console.print("[yellow]用法: ingest <编号>  如: ingest 3 或 ingest 1,3,5[/yellow]")

            else:
                # 如果输入不是命令，当作搜索主题处理
                console.print("[dim]未识别命令，将作为搜索主题处理...[/dim]")
                await app.search_topic(user_input)
                if app.current_papers:
                    do_analyze = Confirm.ask("是否让 AI 分析这些论文？", default=True)
                    if do_analyze:
                        app.analyze_results()
                        if app.last_report:
                            do_save = Confirm.ask("是否保存分析报告到文件？", default=True)
                            if do_save:
                                app.save_report()

        except KeyboardInterrupt:
            console.print("\n[yellow]使用 'quit' 退出程序[/yellow]")
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
