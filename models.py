"""
数据模型 - 论文信息的统一表示
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Paper:
    """论文信息"""
    title: str
    authors: list[str]
    abstract: str = ""
    year: Optional[int] = None
    source: str = ""           # 来源: arxiv / crossref / scopus
    url: str = ""
    doi: str = ""
    citation_count: Optional[int] = None
    venue: str = ""            # 发表期刊/会议
    pdf_url: str = ""
    categories: list[str] = field(default_factory=list)
    arxiv_id: str = ""         # arXiv ID
    depth: int = 0              # 搜索深度层级（1=直接搜索, 2=引用文献, ...）
    graphical_abstract: str = ""  # 图形摘要图片 URL（CrossRef/link 字段获取）
    eid: str = ""               # Scopus EID（用于构造公开链接）
    stars: int = 0              # 推荐指数 1-5（0=未计算）
    relevance_score: float = 0.0  # 相关性分数 0-1
    affiliations: list[str] = field(default_factory=list)  # 作者所属机构/团队

    @property
    def affiliations_str(self) -> str:
        """返回机构列表的字符串表示（去重，最多3个）"""
        seen = set()
        unique = []
        for a in self.affiliations:
            if a and a not in seen:
                seen.add(a)
                unique.append(a)
                if len(unique) >= 3:
                    break
        return ", ".join(unique) if unique else ""

    @property
    def authors_str(self) -> str:
        if len(self.authors) <= 3:
            return ", ".join(self.authors)
        return f"{', '.join(self.authors[:3])} et al."

    def short_abstract(self, max_len: int = 200) -> str:
        if len(self.abstract) <= max_len:
            return self.abstract
        return self.abstract[:max_len].rsplit(" ", 1)[0] + "..."

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors_str,
            "year": self.year,
            "abstract": self.short_abstract(300),
            "url": self.url,
            "doi": self.doi,
            "citations": self.citation_count,
            "venue": self.venue,
            "source": self.source,
            "depth": self.depth,
        }
