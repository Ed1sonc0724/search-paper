"""
科研绘图辅助 — AI 从摘要提取论文专属节点，生成简洁 Mermaid 流程图。
"""
import re
from dataclasses import dataclass
from pathlib import Path

from models import Paper


@dataclass
class PaperVisual:
    title: str
    visual_type: str
    mermaid: str
    markdown: str
    path: Path | None = None


@dataclass
class VisualWriteResult:
    visual: PaperVisual
    path: Path


# ═══════════════════════════════════════════════════════
#  6 类简要模板 — AI 失败时兜底
# ═══════════════════════════════════════════════════════

_FALLBACKS = {
    "review": (
        "文献综述",
        """flowchart LR
  A[研究领域] --> B[方法分类]
  B --> C[关键挑战]
  C --> D[未来方向]""",
    ),
    "experiment": (
        "实验研究",
        """flowchart LR
  A[样品制备] --> B[表征手段]
  B --> C[关键发现]
  C --> D[机制解释]""",
    ),
    "simulation": (
        "数值仿真",
        """flowchart LR
  A[物理模型] --> B[数值方法]
  B --> C[关键参数]
  C --> D[仿真结果]""",
    ),
    "theory": (
        "理论推导",
        """flowchart LR
  A[基本假设] --> B[控制方程]
  B --> C[求解方法]
  C --> D[理论预测]""",
    ),
    "ai": (
        "AI/数据驱动",
        """flowchart LR
  A[数据/输入] --> B[模型架构]
  B --> C[训练策略]
  C --> D[预测/应用]""",
    ),
    "mechanism": (
        "机理分析",
        """flowchart LR
  A[现象观察] --> B[关键因素]
  B --> C[因果机制]
  C --> D[结论启示]""",
    ),
}


def _classify_keywords(paper: Paper) -> str:
    """快速关键词分类"""
    text = f"{paper.title or ''} {paper.abstract or ''}".lower()
    if any(k in text for k in ["review", "survey", "progress", "perspective"]):
        return "review"
    if any(k in text for k in ["machine learning", "neural network", "surrogate", "pinn", "deeponet"]):
        return "ai"
    if any(k in text for k in ["theory", "theoretical", "variational", "governing equation", "analytical"]):
        return "theory"
    if any(k in text for k in ["simulation", "finite element", "fem ", "phase-field", "phase field", "comsol"]):
        return "simulation"
    if any(k in text for k in ["experiment", "sem", "tem", "xrd", "characterization", "synthesis"]):
        return "experiment"
    return "mechanism"


# ═══════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════

def build_paper_visual(paper: Paper, agent=None) -> PaperVisual:
    """
    生成论文科研示意图。
    优先用 AI 从摘要提取专属节点，关键词模板兜底。
    """

    # 优先：AI 生成专属内容
    if agent is not None:
        try:
            ai = agent.explain_visual(paper)
            mm = ai.get("mermaid", "")
            vt = ai.get("visual_type", "机理分析")
            # AI 有效输出：包含 flowchart 且有论文专属节点
            if mm and "flowchart" in mm and "N0" in mm:
                return PaperVisual(
                    title=paper.title,
                    visual_type=vt,
                    mermaid=mm,
                    markdown=_build_md(paper.title, vt, mm, True),
                )
        except Exception:
            pass

    # 兜底
    cat = _classify_keywords(paper)
    vt, mm = _FALLBACKS.get(cat, _FALLBACKS["mechanism"])
    return PaperVisual(
        title=paper.title,
        visual_type=vt,
        mermaid=mm,
        markdown=_build_md(paper.title, vt, mm, False),
    )


def _build_md(title: str, vt: str, mm: str, ai: bool) -> str:
    src = "AI 生成" if ai else "模板"
    short = title[:80] + ("..." if len(title) > 80 else "")
    return (
        f"# {short} - 科研示意图\n\n"
        f"- 图类型：{vt}（{src}）\n"
        f"- 论文：{title}\n\n"
        "```mermaid\n"
        f"{mm}\n"
        "```\n"
    )


# ═══════════════════════════════════════════════════════
#  文件写入
# ═══════════════════════════════════════════════════════

def sanitize_slug(value: str, max_len: int = 60) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w一-鿿]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return (text or "visual")[:max_len].strip("-_") or "visual"


def write_paper_visual(paper: Paper, out_dir: Path, index: int) -> VisualWriteResult:
    visual = build_paper_visual(paper)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = sanitize_slug(paper.title, max_len=48)
    path = out_dir / f"paper-{index:03d}-{slug}.md"
    path.write_text(visual.markdown, encoding="utf-8")
    visual.path = path
    return VisualWriteResult(visual=visual, path=path)
