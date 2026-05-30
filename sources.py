"""
学术论文搜索源 - arXiv, CrossRef, Scopus
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from models import Paper
from config import Config


class SearchSource(ABC):
    """搜索源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[Paper]:
        ...


# ─────────────────────────────────────────────
#  arXiv
# ─────────────────────────────────────────────
class ArxivSource(SearchSource):
    """arXiv API 搜索 — 含重试与速率限制保护"""

    ARXIV_API = "https://export.arxiv.org/api/query"
    NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    _last_request_time: float = 0.0
    _lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "arXiv"

    async def search(self, query: str, max_results: int = 10) -> list[Paper]:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        import time
        import random

        async with ArxivSource._lock:
            # arXiv 无 API Key，纯 IP 限速。两次请求间隔至少 30s
            elapsed = time.time() - ArxivSource._last_request_time
            min_gap = 30.0 + random.uniform(0, 10)
            if elapsed < min_gap:
                wait = min_gap - elapsed
                print(f"  ⏳ arXiv 冷却中，{wait:.0f}s 后发起请求...")
                await asyncio.sleep(wait)

            # 指数退避重试，最多 2 次（避免阻塞其他源）
            resp = None
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                        resp = await client.get(self.ARXIV_API, params=params)
                    ArxivSource._last_request_time = time.time()

                    if resp.status_code == 429:
                        wait = 10 * (2 ** attempt) + random.uniform(0, 3)
                        print(f"  ⚠ arXiv 频率限制，{wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                        await asyncio.sleep(wait)
                        continue

                    resp.raise_for_status()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        wait = 10 * (2 ** attempt) + random.uniform(0, 3)
                        print(f"  ⚠ arXiv 频率限制，{wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
                        await asyncio.sleep(wait)
                        continue
                    raise
                except Exception as e:
                    if attempt == max_retries - 1:
                        msg = str(e) or type(e).__name__
                        print(f"  ⚠ arXiv 请求失败: {msg}（已跳过，其他源继续）")
                        return []
                    await asyncio.sleep(3)
                    continue

            if resp is None:
                print("  ⚠ arXiv 频率限制，本次搜索已跳过（CrossRef/Scopus/PubMed 继续）")
                return []

        root = ET.fromstring(resp.text)
        papers = []
        for entry in root.findall("atom:entry", self.NS):
            title = entry.findtext("atom:title", "", self.NS).strip().replace("\n", " ")
            # 跳过 arXiv 的 "总结果数" 虚拟条目
            if not title or title.startswith("Error"):
                continue
            abstract = entry.findtext("atom:summary", "", self.NS).strip().replace("\n", " ")
            authors = [a.findtext("atom:name", "", self.NS) for a in entry.findall("atom:author", self.NS)]

            # 机构/团队
            affiliations = []
            for a in entry.findall("atom:author", self.NS):
                affil = a.findtext("arxiv:affiliation", "", self.NS)
                if affil and affil.strip():
                    affiliations.append(affil.strip())

            # 年份
            published = entry.findtext("atom:published", "", self.NS)
            year = int(published[:4]) if published else None

            # 链接
            url = ""
            pdf_url = ""
            for link in entry.findall("atom:link", self.NS):
                if link.get("type") == "text/html":
                    url = link.get("href", "")
                elif link.get("title") == "pdf":
                    pdf_url = link.get("href", "")
            if not url:
                url = entry.findtext("atom:id", "", self.NS)

            # DOI
            doi = entry.findtext("arxiv:doi", "", self.NS)

            # arXiv ID
            entry_id = entry.findtext("atom:id", "", self.NS)  # e.g. http://arxiv.org/abs/2301.12345v1
            arxiv_id = ""
            if entry_id:
                # 提取 arXiv ID (如 2301.12345)
                match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", entry_id)
                if match:
                    arxiv_id = match.group(1)

            # 分类
            categories = [c.get("term", "") for c in entry.findall("atom:category", self.NS)]

            papers.append(Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                source="arXiv",
                url=url,
                doi=doi,
                pdf_url=pdf_url,
                categories=categories,
                arxiv_id=arxiv_id,
                affiliations=affiliations,
            ))
        return papers


# ─────────────────────────────────────────────
#  CrossRef
# ─────────────────────────────────────────────
class CrossRefSource(SearchSource):
    """CrossRef API 搜索"""

    API_BASE = "https://api.crossref.org/works"

    @property
    def name(self) -> str:
        return "CrossRef"

    async def search(self, query: str, max_results: int = 10) -> list[Paper]:
        params = {
            "query": query,
            "rows": max_results,
            "sort": "relevance",
            "order": "desc",
        }
        headers = {
            "User-Agent": "SearchPapersApp/1.0 (mailto:user@example.com)",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.API_BASE, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        papers = []
        for item in data.get("message", {}).get("items", []):
            # 标题
            titles = item.get("title", [])
            title = titles[0] if titles else ""
            # 去除 HTML 标签
            title = re.sub(r"<[^>]+>", "", title)

            # 作者 + 机构
            authors = []
            affiliations = []

            # CrossRef 作者可能在 author / editor / contributor 字段
            author_list = item.get("author") or item.get("editor") or item.get("contributor") or []
            for a in author_list:
                given = a.get("given", "")
                family = a.get("family", "")
                if given or family:
                    authors.append(" ".join(p for p in [given, family] if p))
                else:
                    name = a.get("name", "")
                    if name and name.strip():
                        authors.append(name.strip())
                for aff in a.get("affiliation", []):
                    aff_name = aff.get("name", "") if isinstance(aff, dict) else str(aff)
                    if aff_name and aff_name.strip():
                        affiliations.append(aff_name.strip())

            # 摘要
            abstract = item.get("abstract", "")
            abstract = re.sub(r"<[^>]+>", "", abstract)

            # 年份 — 依次尝试多个日期字段
            year = None
            for date_field in ("published-print", "published-online", "issued", "created"):
                date_info = item.get(date_field)
                if not date_info:
                    continue
                # date-parts 格式: [[2024, 3, 15]]
                if "date-parts" in date_info:
                    parts = date_info["date-parts"]
                    if parts and parts[0] and parts[0][0]:
                        year = int(parts[0][0])
                        break
                # 也可能直接是字符串 "2024-03-15"
                elif isinstance(date_info, str) and len(date_info) >= 4:
                    try:
                        year = int(date_info[:4])
                        break
                    except ValueError:
                        continue

            doi = item.get("DOI", "")
            url = item.get("URL", "")

            # 期刊/会议名：container-title → publisher → institution → event
            venue_list = item.get("container-title", [])
            venue = venue_list[0] if venue_list else ""
            if not venue:
                venue = item.get("publisher", "")
            if not venue:
                # institution 可能是对象数组 [{name: "..."}]
                inst = item.get("institution", [])
                if isinstance(inst, list) and inst:
                    venue = inst[0].get("name", "") if isinstance(inst[0], dict) else str(inst[0])
            if not venue:
                event = item.get("event") or {}
                venue = event.get("name", "") if isinstance(event, dict) else ""
            if not venue:
                venue = item.get("series-title", [""])[0] or ""

            citation_count = item.get("is-referenced-by-count")

            # PDF + 图形摘要（Graphical Abstract）
            pdf_url = ""
            ga_url = ""
            for link_item in item.get("link", []):
                ct = link_item.get("content-type", "")
                link_url = link_item.get("URL", "")
                if "pdf" in ct:
                    pdf_url = link_url
                elif "image" in ct and not ga_url:
                    # CrossRef 的图形摘要通常是 image/gif 或 image/png
                    ga_url = link_url

            papers.append(Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                source="CrossRef",
                url=url,
                doi=doi,
                citation_count=citation_count,
                venue=venue,
                pdf_url=pdf_url,
                graphical_abstract=ga_url,
                affiliations=affiliations,
            ))
        return papers


# ─────────────────────────────────────────────
#  Scopus (Elsevier)
# ─────────────────────────────────────────────
class ScopusSource(SearchSource):
    """Scopus (Elsevier) API 搜索"""

    API_BASE = "https://api.elsevier.com/content/search/scopus"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "Scopus"

    async def search(self, query: str, max_results: int = 10) -> list[Paper]:
        if not self.api_key:
            return []

        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json",
        }
        # Scopus 不认逗号/引号语法，转空格分隔（空格默认 AND）
        scopus_query = query.replace(",", " ").replace('"', " ").strip()
        count = min(max_results, 25)
        params = {
            "query": scopus_query,
            "count": count,
            "sort": "relevancy",
            "field": "dc:title,dc:creator,prism:coverDate,prism:doi,"
                     "citedby-count,prism:publicationName,dc:description,"
                     "prism:url,link,eid,prism:aggregationType",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(self.API_BASE, params=params, headers=headers)
            for retry_wait in (3, 6, 12):
                if resp.status_code != 429:
                    break
                await asyncio.sleep(retry_wait)
                resp = await client.get(self.API_BASE, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        entries = data.get("search-results", {}).get("entry", [])

        papers = []
        for item in entries:
            # 跳过错误条目
            if "error" in item:
                continue

            title = item.get("dc:title", "")

            # 作者 + 机构
            authors = []
            affiliations = []
            author_list = item.get("author", [])
            if author_list:
                for a in author_list:
                    name = a.get("authname") or a.get("given-name", "") + " " + a.get("surname", "")
                    authors.append(name.strip())
                    # 提取机构
                    for aff in a.get("affiliation", []):
                        aff_name = aff.get("$", "") if isinstance(aff, dict) else str(aff)
                        if aff_name and aff_name.strip():
                            affiliations.append(aff_name.strip())
            else:
                creator = item.get("dc:creator", "")
                if creator:
                    authors = [creator]

            # 摘要
            abstract = item.get("dc:description", "") or ""

            # 年份
            year = None
            cover_date = item.get("prism:coverDate", "")
            if cover_date and len(cover_date) >= 4:
                try:
                    year = int(cover_date[:4])
                except ValueError:
                    pass

            doi = item.get("prism:doi", "") or ""
            venue = item.get("prism:publicationName", "") or ""
            citation_count = None
            cited = item.get("citedby-count")
            if cited is not None:
                try:
                    citation_count = int(cited)
                except (ValueError, TypeError):
                    pass

            # URL: 优先 Scopus public URL（由 EID 构造）
            # 不要使用 prism:url（内部 API 地址，校园网也无法直接访问）
            # 不要使用 @ref="scopus" 的 href（同样需要特殊 token）
            eid = item.get("eid", "") or ""
            url = _scopus_eid_to_url(eid) if eid else ""

            papers.append(Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                source="Scopus",
                url=url,
                doi=doi,
                citation_count=citation_count,
                venue=venue,
                eid=eid,
                affiliations=affiliations,
            ))
        return papers


# ─────────────────────────────────────────────
#  PubMed (NCBI E-utilities)
# ─────────────────────────────────────────────
class PubMedSource(SearchSource):
    """PubMed (NCBI) API 搜索 — E-utilities"""

    ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "PubMed"

    async def search(self, query: str, max_results: int = 10) -> list[Paper]:
        api_param = f"&api_key={self.api_key}" if self.api_key else ""
        delay = 0.12 if self.api_key else 0.35  # 有 key: 10/s, 无 key: 3/s

        # ── Step 1: esearch — 获取 PMID 列表 ──
        # PubMed 空格=AND，关键词不宜太多。取前 2-3 个核心词即可
        pubmed_query = query.replace(",", " ").replace('"', " ").strip()
        # 如果关键词太多（>3 个词），只取前几个
        words = pubmed_query.split()
        if len(words) > 4:
            pubmed_query = " ".join(words[:4])
        params = {
            "db": "pubmed",
            "term": pubmed_query,
            "retmax": min(max_results, 50),
            "sort": "relevance",
            "retmode": "json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                self.ESEARCH,
                params=params,
                headers={"User-Agent": "SearchPapersApp/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])

        if not id_list:
            return []

        await asyncio.sleep(delay)

        # ── Step 2: efetch — 获取论文详情 ──
        ids = ",".join(id_list)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                self.EFETCH,
                params={
                    "db": "pubmed",
                    "id": ids,
                    "rettype": "abstract",
                    "retmode": "xml",
                },
                headers={"User-Agent": "SearchPapersApp/1.0"},
            )
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        papers = []
        for article in root.findall(".//PubmedArticle"):
            medline = article.find("MedlineCitation")
            if medline is None:
                continue
            art = medline.find("Article")
            if art is None:
                continue

            # 标题
            title_el = art.find("ArticleTitle")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            # 摘要
            abstract_parts = []
            abstract_el = art.find("Abstract")
            if abstract_el is not None:
                for text_el in abstract_el.findall("AbstractText"):
                    label = text_el.get("Label", "")
                    content = text_el.text or ""
                    if label:
                        abstract_parts.append(f"{label}: {content}")
                    else:
                        abstract_parts.append(content)
            abstract = " ".join(abstract_parts)

            # 作者 + 机构
            authors = []
            affiliations = []
            author_list = art.find("AuthorList")
            if author_list is not None:
                for a in author_list.findall("Author"):
                    last = a.findtext("LastName", "") or ""
                    fore = a.findtext("ForeName", "") or ""
                    name = f"{fore} {last}".strip()
                    if name:
                        authors.append(name)
                    for aff in a.findall(".//AffiliationInfo/Affiliation"):
                        if aff.text and aff.text.strip() and aff.text.strip() not in affiliations:
                            affiliations.append(aff.text.strip())

            # 期刊
            journal_el = art.find("Journal")
            venue = ""
            volume = ""
            if journal_el is not None:
                venue = journal_el.findtext("Title", "") or ""
                ji = journal_el.find("JournalIssue")
                if ji is not None:
                    volume = ji.findtext("Volume", "") or ""

            # 年份
            year = None
            if journal_el is not None:
                ji = journal_el.find("JournalIssue")
                if ji is not None:
                    pd = ji.find("PubDate")
                    if pd is not None:
                        for yt in ("Year", "MedlineDate"):
                            y_el = pd.find(yt)
                            if y_el is not None and y_el.text:
                                try:
                                    year = int(y_el.text[:4])
                                    break
                                except ValueError:
                                    continue

            # PMID — 在 MedlineCitation 层级
            pmid_el = medline.find("PMID")
            pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""

            # DOI — 在 ArticleIdList 或 ELocationID
            doi = ""
            id_list_el = art.find(".//ArticleIdList")
            if id_list_el is not None:
                for aid in id_list_el.findall("ArticleId"):
                    if aid.get("IdType", "") == "doi":
                        doi = aid.text or ""
                        break
            if not doi:
                for eloc in art.findall(".//ELocationID"):
                    if eloc.get("EIdType", "") == "doi":
                        doi = eloc.text or ""
                        break

            # URL
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
            pdf_url = ""
            if doi:
                pdf_url = f"https://doi.org/{doi}"

            papers.append(Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                source="PubMed",
                url=url,
                doi=doi,
                venue=venue,
                pdf_url=pdf_url,
                affiliations=affiliations,
            ))

        return papers


# ─────────────────────────────────────────────
#  URL 归一化
# ─────────────────────────────────────────────

def _doi_to_url(doi: str) -> str:
    """将 DOI 转换为可直接访问的出版商链接（校园网优先）"""
    if not doi:
        return ""
    doi = doi.strip()
    # 如果已是完整 URL，取出 DOI 部分
    if doi.startswith("http"):
        # 提取 doi.org/ 后面的部分
        m = re.search(r"doi\.org/(.+)", doi)
        if m:
            doi = m.group(1)
    return f"https://doi.org/{doi}"


def _arxiv_id_to_url(arxiv_id: str, pdf: bool = False) -> str:
    """将 arXiv ID 转换为可访问链接"""
    if not arxiv_id:
        return ""
    if pdf:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return f"https://arxiv.org/abs/{arxiv_id}"


def _title_to_google_scholar_url(title: str) -> str:
    """将论文标题转换为 Google Scholar 搜索链接（保底方案）"""
    import urllib.parse
    encoded = urllib.parse.quote(title)
    return f"https://scholar.google.com/scholar?q={encoded}"


def _title_to_semantic_scholar_url(title: str) -> str:
    """将论文标题转换为 Semantic Scholar 搜索链接（保底方案）"""
    import urllib.parse
    encoded = urllib.parse.quote(title)
    return f"https://www.semanticscholar.org/search?q={encoded}&sort=relevance"


def _scopus_eid_to_url(eid: str) -> str:
    """将 Scopus EID 转换为可访问的公开链接（已废弃，返回空）"""
    # Scopus 旧版 URL 格式已废弃，不再使用
    return ""


def normalize_paper_urls(all_results: dict[str, list[Paper]]) -> dict[str, list[Paper]]:
    """
    统一 URL 策略：
    1. 有 DOI → doi.org 直链（校园网直接访问出版商）
    2. 无 DOI 但有 arXiv ID → arXiv 官方链接
    3. 无任何 ID → Google Scholar / Semantic Scholar 标题搜索（保底）
    - 避免使用 Scopus URL（已废弃）和 ELSEVIER 内部 API URL
    """
    title_key_to_url: dict[str, str] = {}

    # 第一遍：建立 title -> 最佳 URL 的映射
    for source_name, papers in all_results.items():
        for p in papers:
            key = p.title.lower().strip()
            if key in title_key_to_url:
                continue

            url = ""

            # 优先级 1：DOI → doi.org 直链
            if p.doi:
                url = _doi_to_url(p.doi)

            # 优先级 2：arXiv → arXiv 官方链接
            elif p.arxiv_id:
                url = _arxiv_id_to_url(p.arxiv_id)

            # 优先级 3：以上都没有 → Google Scholar 标题搜索
            if not url:
                url = _title_to_google_scholar_url(p.title)

            if url:
                title_key_to_url[key] = url

    # 第二遍：用归一化后的 URL 替换所有论文的 url
    for source_name, papers in all_results.items():
        for p in papers:
            key = p.title.lower().strip()
            if key in title_key_to_url:
                p.url = title_key_to_url[key]
            # 对于无 DOI 的论文，同时记一个 Semantic Scholar 保底链接
            if not p.doi and not p.arxiv_id:
                p.graphical_abstract = _title_to_semantic_scholar_url(p.title)

    return all_results


async def fetch_references_by_doi(doi: str) -> list[str]:
    """通过 DOI 从 CrossRef 获取该论文引用文献的 DOI 列表"""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_CROSSREF_HEADERS)
            if resp.status_code != 200:
                return []
        data = resp.json()
        refs = data.get("message", {}).get("reference", [])
        return [r["DOI"] for r in refs if "DOI" in r]
    except Exception:
        return []


async def fetch_paper_by_doi(doi: str) -> Optional[Paper]:
    """通过 DOI 从 CrossRef 获取单篇论文信息"""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_CROSSREF_HEADERS)
            if resp.status_code != 200:
                return None
        item = resp.json().get("message", {})

        # 解析论文信息（同 CrossRefSource 逻辑）
        titles = item.get("title", [])
        title = titles[0] if titles else ""
        title = re.sub(r"<[^>]+>", "", title)
        if not title:
            return None

        authors = []
        affiliations = []
        for a in item.get("author", []):
            name_parts = [a.get("given", ""), a.get("family", "")]
            name = " ".join(p for p in name_parts if p)
            if name:
                authors.append(name)
            for aff in a.get("affiliation", []):
                aff_name = aff.get("name", "") if isinstance(aff, dict) else str(aff)
                if aff_name and aff_name.strip() and aff_name.strip() not in affiliations:
                    affiliations.append(aff_name.strip())

        abstract = re.sub(r"<[^>]+>", "", item.get("abstract", ""))

        year = None
        for date_field in ("published-print", "published-online"):
            date_info = item.get(date_field)
            if date_info and "date-parts" in date_info:
                parts = date_info["date-parts"]
                if parts and parts[0] and parts[0][0]:
                    year = int(parts[0][0])
                    break

        url_val = item.get("URL", "")
        venue_list = item.get("container-title", [])
        venue = venue_list[0] if venue_list else ""
        if not venue:
            venue = item.get("publisher", "")
        if not venue:
            inst = item.get("institution", [])
            if isinstance(inst, list) and inst:
                venue = inst[0].get("name", "") if isinstance(inst[0], dict) else str(inst[0])
        if not venue:
            event = item.get("event") or {}
            venue = event.get("name", "") if isinstance(event, dict) else ""
        if not venue:
            venue = item.get("series-title", [""])[0] or ""
        citation_count = item.get("is-referenced-by-count")

        pdf_url = ""
        ga_url = ""
        for link_item in item.get("link", []):
            ct = link_item.get("content-type", "")
            link_url = link_item.get("URL", "")
            if "pdf" in ct:
                pdf_url = link_url
            elif "image" in ct and not ga_url:
                ga_url = link_url

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            source="CrossRef",
            url=url_val,
            doi=item.get("DOI", doi),
            citation_count=citation_count,
            venue=venue,
            pdf_url=pdf_url,
            graphical_abstract=ga_url,
            affiliations=affiliations,
        )
    except Exception:
        return None

async def search_all_sources(
    query: str,
    config: Config,
    sources: Optional[list[str]] = None,
) -> dict[str, list[Paper]]:
    """
    并行搜索多个源，返回 {source_name: [Paper, ...]}
    sources: 可指定 ["arxiv", "crossref", "scopus"]，默认搜索全部
    """
    all_sources: dict[str, SearchSource] = {
        "arxiv": ArxivSource(),
        "crossref": CrossRefSource(),
        "scopus": ScopusSource(api_key=config.scopus_api_key),
        "pubmed": PubMedSource(api_key=config.pubmed_api_key),
    }

    if sources:
        selected = {k: v for k, v in all_sources.items() if k in sources}
    else:
        selected = all_sources

    async def _search_one(src: SearchSource) -> tuple[str, list[Paper]]:
        try:
            papers = await src.search(query, max_results=config.max_results_per_source)
            return src.name, papers
        except Exception as e:
            print(f"  ⚠ {src.name} 搜索失败: {e}")
            return src.name, []

    task_map = {asyncio.create_task(_search_one(src)): src.name for src in selected.values()}
    done, pending = await asyncio.wait(task_map.keys(), timeout=150.0)
    for t in pending:
        t.cancel()
        print(f"  ⚠ {task_map[t]}: 超时取消")
    results = {}
    for t in done:
        try:
            name, papers = t.result()
            results[name] = papers
        except Exception as e:
            print(f"  ⚠ {task_map.get(t, '?')}: 异常 - {e}")
    return normalize_paper_urls(results)


# ─────────────────────────────────────────────
#  深度搜索（递归追踪引用文献）
# ─────────────────────────────────────────────
async def deep_search(
    query: str,
    config: Config,
    depth: int = 1,
    sources: Optional[list[str]] = None,
    on_depth_start=None,
) -> dict[str, list[Paper]]:
    """
    深度搜索论文及其引用文献。

    depth=1: 只搜索第一层论文（默认行为）
    depth=2: 搜索第一层 + 提取第一层论文的引用文献
    depth=N: 递归深入到第 N 层引用

    on_depth_start: 回调函数 (current_depth, total_depth)，用于进度提示
    """
    if depth < 1:
        depth = 1

    all_results: dict[str, list[Paper]] = {}
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()

    def _dedup_and_add(
        papers: list[Paper], source_key: str, current_depth: int
    ) -> list[Paper]:
        """去重并添加论文到结果集"""
        added = []
        for p in papers:
            title_key = p.title.lower().strip()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            if p.doi:
                doi_key = p.doi.lower()
                if doi_key in seen_dois:
                    continue
                seen_dois.add(doi_key)
            p.depth = current_depth
            all_results.setdefault(source_key, []).append(p)
            added.append(p)
        return added

    # ── 第 1 层：正常多源搜索 ──
    if on_depth_start:
        on_depth_start(1, depth)

    results = await search_all_sources(query, config, sources)
    current_level_papers: list[Paper] = []
    for source_name, papers in results.items():
        added = _dedup_and_add(papers, source_name, 1)
        current_level_papers.extend(added)

    if depth == 1:
        return all_results

    # ── 第 2 层及以后：通过引用文献深入 ──
    semaphore = asyncio.Semaphore(5)  # 并发控制，避免触发 API 限流

    async def _fetch_refs_limited(doi: str) -> list[str]:
        async with semaphore:
            await asyncio.sleep(0.1)  # 小延迟，友好访问
            return await fetch_references_by_doi(doi)

    async def _fetch_paper_limited(doi: str) -> Optional[Paper]:
        async with semaphore:
            await asyncio.sleep(0.1)
            return await fetch_paper_by_doi(doi)

    for d in range(2, depth + 1):
        if not current_level_papers:
            break

        if on_depth_start:
            on_depth_start(d, depth)

        # 收集有 DOI 的论文（去重）
        doi_map: dict[str, str] = {}
        for p in current_level_papers:
            if p.doi:
                doi_map.setdefault(p.doi.lower(), p.doi)
        dois_to_fetch = list(doi_map.values())[:20]  # 最多处理 20 篇论文的引用

        if not dois_to_fetch:
            break

        # 批量获取引用文献的 DOI 列表
        ref_results = await asyncio.gather(*[_fetch_refs_limited(doi) for doi in dois_to_fetch])
        ref_dois_all: list[str] = []
        for refs in ref_results:
            ref_dois_all.extend(refs)

        # 去重（跳过已有论文）
        new_dois: list[str] = []
        new_dois_set: set[str] = set()
        for doi in ref_dois_all:
            doi_lower = doi.lower()
            if doi_lower not in seen_dois and doi_lower not in new_dois_set:
                new_dois_set.add(doi_lower)
                new_dois.append(doi)

        # 限制数量
        max_refs = config.max_results_per_source * 3
        new_dois = new_dois[:max_refs]

        if not new_dois:
            break

        # 批量获取论文详细信息
        paper_results = await asyncio.gather(*[_fetch_paper_limited(doi) for doi in new_dois])
        new_papers = [p for p in paper_results if p is not None]

        source_key = f"引用文献 (深度{d})"
        current_level_papers = _dedup_and_add(new_papers, source_key, d)

    # 最终归一化：确保所有论文 URL 都是可直接访问的 DOI/公开链接
    return normalize_paper_urls(all_results)


# ─────────────────────────────────────────────
#  推荐指数计算（1-5 星）
# ─────────────────────────────────────────────

def compute_star_ratings(papers: list[Paper], topic: str, search_terms: list[str] = None):
    """
    为论文列表计算推荐指数（stars 1-5），百分位制。

    综合考虑四个维度打出综合分，然后按排名分配星级：
    - 5 星：Top 3 或前 15%（至少有 1 篇，最多 3 篇满星）
    - 4 星：15%-40%
    - 3 星：40%-65%
    - 2 星：65%-85%
    - 1 星：最后 15%
    """
    if not papers:
        return

    current_year = 2026
    if not search_terms:
        search_terms = [w.lower() for w in topic.split() if len(w) > 2]

    max_citations = max((p.citation_count or 0) for p in papers)
    if max_citations == 0:
        max_citations = 1

    # 计算每篇的综合分
    scored = []
    for paper in papers:
        # ── 1. 相关性（权重 50%，主导地位）──
        title_lower = paper.title.lower()
        abstract_lower = (paper.abstract or "").lower()

        term_scores = []
        for term in search_terms:
            t = term.lower().strip()
            if not t:
                continue

            n_title = title_lower.count(t)     # 标题中出现的次数
            n_abstract = abstract_lower.count(t)  # 摘要中出现的次数
            is_multiword = len(t.split()) >= 2  # 多词短语更有区分度

            if n_title > 0:
                # 标题命中：基础 0.8，每次额外出现 +0.1，上限 1.0
                score = min(0.8 + n_title * 0.1, 1.0)
                if is_multiword:
                    score = min(score * 1.2, 1.0)  # 多词短语在标题命中 = 强烈信号
            elif n_abstract > 0:
                # 摘要命中：基础 0.5，每次额外出现 +0.05，上限 0.8
                score = min(0.5 + n_abstract * 0.05, 0.8)
                if is_multiword:
                    score = min(score * 1.2, 0.9)
            else:
                score = 0.0  # 未命中

            term_scores.append(score)

        relevance = sum(term_scores) / max(len(term_scores), 1) if term_scores else 0.0

        # ── 2. 引用（权重 25%）──
        import math
        citations = paper.citation_count or 0
        citation_score = math.log(1 + citations) / math.log(1 + max_citations) if max_citations > 0 else 0

        # ── 3. 时效（权重 15%）──
        year = paper.year or current_year
        age = max(current_year - year, 0)
        recency_score = max(1.0 - age * 0.06, 0.3)

        # ── 4. 来源（权重 10%）──
        if paper.source in ("CrossRef", "Scopus") and paper.venue:
            source_score = 1.0
        elif paper.source == "arXiv":
            source_score = 0.7
        else:
            source_score = 0.85

        # ── 加权组合 ──
        combined = (
            0.50 * relevance +
            0.25 * citation_score +
            0.15 * recency_score +
            0.10 * source_score
        )
        scored.append((paper, combined, relevance))

    # 按综合分排序
    scored.sort(key=lambda x: x[1], reverse=True)
    n = len(scored)

    # 按排名百分位分配星级：保证 1-3 篇满星
    for rank, (paper, combined, relevance) in enumerate(scored):
        percentile = rank / max(n - 1, 1)  # 0.0 = best, 1.0 = worst
        if percentile <= 0.15 or rank < min(3, n):  # Top 3 或前 15%
            stars = 5
        elif percentile <= 0.40:
            stars = 4
        elif percentile <= 0.65:
            stars = 3
        elif percentile <= 0.85:
            stars = 2
        else:
            stars = 1

        paper.relevance_score = round(relevance, 2)
        paper.stars = stars


# ─────────────────────────────────────────────
#  Semantic Scholar — 补全引用数 + 机构信息
# ─────────────────────────────────────────────

async def _fetch_s2_data(title: str, doi: str = "") -> dict:
    """通过 Semantic Scholar API 获取引用数和机构（免费，无需 API Key）"""
    import urllib.parse
    fields = "citationCount,authors"
    try:
        if doi:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?fields={fields}"
        else:
            url = f"https://api.semanticscholar.org/graph/v1/paper/search/match?query={urllib.parse.quote(title)}&fields={fields}"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "SearchPapersApp/1.0"})
            if resp.status_code != 200:
                return {}
            data = resp.json()

        # DOI 直查返回的是 paper 对象
        if "citationCount" in data:
            paper = data
        # search/match 返回的是 {data: [paper, ...]}
        elif "data" in data and data["data"]:
            paper = data["data"][0]
        else:
            return {}

        # 提取作者名 + 机构
        s2_authors = []
        affiliations = []
        for author in paper.get("authors", []):
            author_name = author.get("name", "") or ""
            if author_name and author_name.strip():
                s2_authors.append(author_name.strip())
            for affil in author.get("affiliations", []):
                if affil and affil.strip() and affil.strip() not in affiliations:
                    affiliations.append(affil.strip())

        return {
            "citation_count": paper.get("citationCount"),
            "authors": s2_authors,
            "affiliations": affiliations,
        }
    except Exception:
        return {}


async def _fetch_crossref_detail(doi: str) -> dict:
    """通过 CrossRef /works/{doi} 获取作者和机构（比搜索结果更详细）"""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "SearchPapersApp/1.0"})
            if resp.status_code != 200:
                return {}
        item = resp.json().get("message", {})
        if not item:
            return {}

        # 作者
        authors = []
        affiliations = []
        author_list = item.get("author") or item.get("editor") or item.get("contributor") or []
        for a in author_list:
            name_parts = [a.get("given", ""), a.get("family", "")]
            name = " ".join(p for p in name_parts if p)
            if not name:
                name = a.get("name", "").strip()
            if name:
                authors.append(name)
            for aff in a.get("affiliation", []):
                aff_name = aff.get("name", "") if isinstance(aff, dict) else str(aff)
                if aff_name and aff_name.strip() and aff_name.strip() not in affiliations:
                    affiliations.append(aff_name.strip())

        return {
            "authors": authors,
            "affiliations": affiliations,
        }
    except Exception:
        return {}


async def _fetch_openalex_affiliations(doi: str) -> list[str]:
    """通过 OpenAlex API 获取机构（免费，无需 Key）"""
    import urllib.parse
    url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "SearchPapersApp/1.0"})
            if resp.status_code != 200:
                return []
        data = resp.json()
        affiliations = []
        for authorship in data.get("authorships", []):
            for inst in authorship.get("institutions", []):
                name = inst.get("display_name", "")
                if name and name not in affiliations:
                    affiliations.append(name)
        return affiliations
    except Exception:
        return []


async def backfill_citations(papers: list[Paper]):
    """通过 Semantic Scholar 补充缺失的引用数和缺失的作者名"""
    needs_fill = [p for p in papers if p.citation_count is None or not p.authors]

    if not needs_fill:
        return

    sem = asyncio.Semaphore(5)

    async def _fill_one(p: Paper):
        async with sem:
            s2 = await _fetch_s2_data(p.title, p.doi)
            if not s2:
                # Semantic Scholar 失败，试试 CrossRef 详情接口
                if p.doi and not p.authors:
                    crossref = await _fetch_crossref_detail(p.doi)
                    if crossref and crossref.get("authors"):
                        p.authors = crossref["authors"]
                    if crossref and crossref.get("affiliations"):
                        p.affiliations = crossref["affiliations"]
                return

            if s2.get("citation_count") is not None and p.citation_count is None:
                p.citation_count = s2["citation_count"]

            if s2.get("authors") and not p.authors:
                p.authors = s2["authors"]

            if s2.get("affiliations") and not p.affiliations:
                p.affiliations = s2["affiliations"]

    await asyncio.gather(*[_fill_one(p) for p in needs_fill])
