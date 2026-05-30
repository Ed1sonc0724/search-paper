"""
Wiki Bridge — 连接 Search Papers（arXiv/CrossRef/Scopus/PubMed）与 wiki 知识库的桥接模块

职责（精简）：
- 重复检测（DOI > 标题 > 文件名）
- 下载论文 PDF 到 raw/literature/
- 写入元数据桩 .md 到 sources/literature/（含下载链接）
- 返回结构化数据，供 wiki agent 按 CLAUDE.md 工作流完成详细写作

wiki agent 负责（按 wiki/CLAUDE.md 工作流）:
- Step 1: 读取 PDF，判断文献类型（review/research）
- Step 2: 创建详细 source 摘要页（核心研究问题、模型框架、关键发现、创新点等）
- Step 3: 更新相关实体/概念页面（双向链接）
- Step 4: 更新 wiki/index.md
- Step 5: 更新 wiki/log.md
- 执行 post-ingest 检查清单
"""
import os
import re
import sys
import json
import time
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse
from difflib import SequenceMatcher

from models import Paper
from agent import DeepSeekAgent


# ── 路径常量 ──────────────────────────────────
# WIKI_BASE can be overridden via environment variable for custom wiki locations
_WIKI_BASE = os.environ.get("SEARCH_PAPERS_WIKI_DIR")
if _WIKI_BASE:
    WIKI_ROOT = Path(_WIKI_BASE).resolve()
else:
    WIKI_ROOT = Path(__file__).resolve().parent / "wiki"
SOURCES_DIR = WIKI_ROOT / "sources" / "literature"
RAW_DIR = WIKI_ROOT / "raw" / "literature"
INDEX_PATH = WIKI_ROOT / "index.md"
LOG_PATH = WIKI_ROOT / "log.md"
CONCEPTS_DIR = WIKI_ROOT / "concepts"
ENTITIES_DIR = WIKI_ROOT / "entities"

# wiki CLAUDE.md 路径（供 agent 读取，可选）
WIKI_CLAUDE_MD = WIKI_ROOT / "CLAUDE.md"


# ── 期刊全名 → 缩写映射 ──────────────────────
JOURNAL_ABBREV = {
    "Journal of the Mechanics and Physics of Solids": "JMPS",
    "Engineering Fracture Mechanics": "EFM",
    "International Journal of Mechanical Sciences": "IJMS",
    "International Journal of Solids and Structures": "IJSS",
    "Journal of Power Sources": "JPS",
    "Journal of the Electrochemical Society": "JES",
    "Journal of Materials Chemistry A": "JMCA",
    "Acta Materialia": "AM",
    "Computational Mechanics": "CM",
    "Computer Methods in Applied Mechanics and Engineering": "CMAAME",
    "ACS Applied Materials & Interfaces": "ACS-AMI",
    "Advanced Energy Materials": "AEM",
    "Advanced Materials": "AM",
    "Advanced Materials Research": "AMR",
    "Electrochimica Acta": "EA",
    "Modelling and Simulation in Materials Science and Engineering": "MSMSE",
    "Physical Review Materials": "PRM",
    "Nature Materials": "NM",
    "Nature Energy": "NE",
    "Nature Communications": "NC",
    "Science": "Science",
    "Nano Letters": "NL",
    "Nano Energy": "NanoEnergy",
    "Energy & Environmental Science": "EES",
    "Journal of Computational Physics": "JCP",
    "Theoretical and Applied Fracture Mechanics": "TAFM",
    "Numerical Methods for Partial Differential Equations": "NMPDE",
    "Extreme Mechanics Letters": "EML",
    "Cell Reports Physical Science": "CellRPS",
    "Joule": "Joule",
    "Chemistry of Materials": "CM",
}


def _guess_journal_abbrev(venue: str) -> str:
    """从期刊全名推断缩写"""
    if not venue:
        return ""
    venue = venue.strip()
    if venue in JOURNAL_ABBREV:
        return JOURNAL_ABBREV[venue]
    for full, abbr in JOURNAL_ABBREV.items():
        if full.lower() == venue.lower():
            return abbr
    words = venue.split()
    if len(words) >= 2:
        return "".join(w[0].upper() for w in words if w[0].isalpha())
    return venue[:8].replace(" ", "")


class WikiBridge:
    """Wiki 桥接器 — PDF 下载 + 元数据桩，详细写作交给 wiki agent"""

    def __init__(self, agent: DeepSeekAgent):
        self.agent = agent
        self._existing_sources: Optional[dict] = None
        self._existing_concepts: Optional[set] = None
        self._existing_entities: Optional[set] = None

    # ── 公共 API ──────────────────────────────

    def ingest_paper(self, paper: Paper, topic: str = "") -> dict:
        """
        摄入单篇论文：
        1. 重复检测
        2. 下载 PDF 到 raw/literature/
        3. 写元数据桩 .md 到 sources/literature/（含 PDF 下载链接）
        4. 更新 log.md

        返回 {"status": "created"|"skipped"|"error", ...}
        调用方拿到结果后应启动 wiki agent 完成 CLAUDE.md 工作流。
        """
        # 1. 重复检测
        dup = self._check_duplicate(paper)
        if dup["is_dup"]:
            return {"status": "skipped", "reason": dup["reason"], "existing": dup.get("existing_path", "")}

        # 2. 生成文件名
        abbrev = _guess_journal_abbrev(paper.venue)
        year = paper.year or datetime.now().year
        filename = self._resolve_filename(abbrev, year, paper)
        page_id = filename.replace(".md", "")

        # 3. 下载 PDF 到 raw/literature/
        pdf_name, pdf_diag = self._download_pdf(paper, filename)

        # 4. 写元数据桩 .md（仅 frontmatter + 信息表 + 下载链接，不含详细分析）
        content = self._build_metadata_stub(paper, pdf_name or "", topic)
        filepath = SOURCES_DIR / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")

        # 5. 更新内存缓存
        sources = self._load_existing_sources()
        sources["filenames"].add(filename)
        if paper.doi:
            sources["by_doi"][paper.doi.strip().lower()] = filename
        sources["by_title"][paper.title.strip().lower()] = filename

        # 6. 更新 log.md（记录操作）
        self._append_log(filename, paper, pdf_name or "")

        result = {
            "status": "created",
            "page_id": page_id,
            "path": str(filepath),
            "filename": filename,
            "pdf": pdf_name,
            "pdf_path": str(RAW_DIR / pdf_name) if pdf_name else "",
            "pdf_diag": pdf_diag,
            "paper": {
                "title": paper.title,
                "authors": paper.authors_str,
                "year": paper.year,
                "journal": paper.venue,
                "doi": paper.doi,
                "abstract": paper.abstract[:500] if paper.abstract else "",
                "citation_count": paper.citation_count,
                "source": paper.source,
                "url": paper.url,
                "arxiv_id": paper.arxiv_id,
            },
        }

        # 信号：需要 wiki agent 处理的页面列表
        self._pending_for_agent = getattr(self, "_pending_for_agent", [])
        self._pending_for_agent.append(result)

        return result

    def ingest_papers(self, papers: list[Paper], topic: str = "") -> list[dict]:
        """批量摄入多篇论文"""
        results = []
        for paper in papers:
            result = self.ingest_paper(paper, topic)
            results.append(result)
        return results

    def get_pending_for_agent(self) -> list[dict]:
        """获取等待 wiki agent 处理的论文列表"""
        return getattr(self, "_pending_for_agent", [])

    def has_duplicate(self, paper: Paper) -> bool:
        """快速检查是否已存在"""
        return self._check_duplicate(paper)["is_dup"]

    # ── PDF 下载 ──────────────────────────────

    # 模拟浏览器 User-Agent，避免出版商拒绝请求
    _UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    def _download_pdf(self, paper: Paper, base_filename: str):
        """
        下载论文 PDF 到 raw/literature/。

        三阶段策略:
        Phase 1 — 直接 PDF 源（arXiv 直链，最快）
        Phase 2 — DOI → HTML 解析提取 PDF 链接（校园网/IP 认证）
        Phase 3 — Unpaywall OA 兜底

        返回 (pdf_name_or_None, diagnostics_list)
        """
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        pdf_name = base_filename.replace(".md", ".pdf")
        pdf_path = RAW_DIR / pdf_name
        diag = []

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            diag.append(f"PDF 已存在: {pdf_path}")
            return pdf_name, diag

        src = paper.source or "unknown"
        diag.append(f"来源: {src}, arxiv_id={'有' if paper.arxiv_id else '无'}, pdf_url={'有' if paper.pdf_url else '无'}, doi={paper.doi or '无'}")

        # ── Phase 1: 直接 PDF URL ──
        direct_urls = []
        if paper.pdf_url:
            direct_urls.append(("pdf_url", paper.pdf_url))
        if paper.arxiv_id:
            direct_urls.append(("arxiv_id", f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"))

        for label, url in direct_urls:
            diag.append(f"Phase1 [{label}]: 尝试 {url[:100]}...")
            ok = self._download_url(url, pdf_path)
            if ok:
                diag.append(f"Phase1 [{label}]: 成功")
                return ok, diag
            diag.append(f"Phase1 [{label}]: 失败")

        if not direct_urls:
            diag.append("Phase1: 无直接 PDF 源（非 arXiv 论文），跳过")

        # ── Phase 2: DOI → HTML 解析提取 PDF 链接 ──
        if paper.doi:
            diag.append(f"Phase2 [DOI]: {paper.doi}")
            result, doi_diag = self._download_via_doi(paper.doi, pdf_path)
            diag.extend(doi_diag)
            if result:
                return result, diag
        else:
            diag.append("Phase2: 无 DOI，跳过")

        # ── Phase 3: Unpaywall OA 兜底 ──
        if paper.doi:
            diag.append("Phase3 [Unpaywall]: 尝试开放获取...")
            result = self._download_via_unpaywall(paper.doi, pdf_path)
            if result:
                diag.append("Phase3 [Unpaywall]: 成功")
                return result, diag
            diag.append("Phase3 [Unpaywall]: 无 OA 版本")
        else:
            diag.append("Phase3: 无 DOI，跳过")

        diag.append("所有阶段均失败")
        return None, diag

    def _download_url(self, url: str, pdf_path: Path) -> Optional[str]:
        """通用 URL 下载，验证 PDF 文件头"""
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": self._UA})
                if resp.status_code == 200 and self._is_pdf(resp):
                    pdf_path.write_bytes(resp.content)
                    return pdf_path.name
        except Exception:
            pass
        return None

    def _download_via_doi(self, doi: str, pdf_path: Path):
        """
        通过 DOI 获取 PDF。
        doi.org 通常 302 重定向到出版商 HTML 页面，
        本方法从 HTML 中提取真正的 PDF 下载链接后二次请求。
        校园网用户通过 IP 认证自动获得订阅权限。

        返回 (pdf_name_or_None, diagnostics_list)
        """
        doi_url = f"https://doi.org/{doi}"
        diag = []

        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                resp = client.get(doi_url, headers={"User-Agent": self._UA})
                final_url = str(resp.url)
                diag.append(f"  DOI → HTTP {resp.status_code}, final: {final_url[:120]}")

                # MDPI (10.3390): 全开放获取，403 是反爬，直接拼 PDF URL
                if "mdpi.com" in final_url:
                    diag.append("  检测到 MDPI 开放获取期刊")
                    # URL 格式: https://www.mdpi.com/ISSN/vol/iss/num → .../pdf
                    pdf_url = final_url.rstrip("/") + "/pdf"
                    diag.append(f"  尝试 MDPI PDF: {pdf_url[:120]}")
                    try:
                        resp2 = client.get(pdf_url, headers={
                            "User-Agent": self._UA,
                            "Accept": "application/pdf",
                        })
                        if resp2.status_code == 200 and self._is_pdf(resp2):
                            pdf_path.write_bytes(resp2.content)
                            diag.append(f"  MDPI PDF 下载成功 ({len(resp2.content)} bytes)")
                            return pdf_path.name, diag
                        diag.append(f"  MDPI PDF 请求: HTTP {resp2.status_code}")
                    except Exception as e:
                        diag.append(f"  MDPI PDF 异常: {e}")
                    return None, diag

                if resp.status_code != 200:
                    diag.append(f"  DOI 返回非 200")
                    return None, diag

                ct = resp.headers.get("content-type", "")
                diag.append(f"  Content-Type: {ct[:80]}")

                # 情况 A: DOI 直接重定向到了 PDF
                if self._is_pdf(resp):
                    diag.append("  直接返回 PDF，写入...")
                    pdf_path.write_bytes(resp.content)
                    return pdf_path.name, diag

                # 情况 B: Elsevier linkinghub JS 跳转页 → 构造 ScienceDirect URL
                if "linkinghub.elsevier.com" in final_url or "sciencedirect.com" in final_url:
                    diag.append("  检测到 Elsevier/ScienceDirect，尝试专用处理...")
                    sd_result, sd_diag = self._handle_sciencedirect(final_url, doi, client, pdf_path)
                    diag.extend(sd_diag)
                    if sd_result:
                        return sd_result, diag

                # 情况 C: 通用 HTML 页面 → 提取 PDF 链接
                if "html" in ct:
                    pdf_url = self._extract_pdf_from_html(resp.text, final_url)
                    if not pdf_url:
                        diag.append("  HTML 中未提取到 PDF 链接")
                        if "citation_pdf_url" in resp.text:
                            diag.append("  (HTML 中包含 citation_pdf_url 但正则未匹配)")
                        return None, diag

                    diag.append(f"  提取到 PDF: {pdf_url[:150]}")
                    try:
                        resp2 = client.get(pdf_url, headers={
                            "User-Agent": self._UA,
                            "Referer": final_url,
                        })
                        ct2 = resp2.headers.get("content-type", "")
                        diag.append(f"  PDF 请求: HTTP {resp2.status_code}, ct={ct2[:60]}")

                        if resp2.status_code == 200 and self._is_pdf(resp2):
                            pdf_path.write_bytes(resp2.content)
                            diag.append(f"  下载成功 ({len(resp2.content)} bytes)")
                            return pdf_path.name, diag
                        elif resp2.status_code in (401, 403):
                            diag.append(f"  被拒绝 (HTTP {resp2.status_code}) — 需登录或 IP 认证失败")
                        elif resp2.status_code == 302:
                            diag.append(f"  被重定向 (可能跳转到登录页)")
                        else:
                            diag.append(f"  失败: HTTP {resp2.status_code}")
                    except Exception as e:
                        diag.append(f"  PDF 下载异常: {e}")
                else:
                    diag.append(f"  非 HTML 也非 PDF，无法处理")
        except Exception as e:
            diag.append(f"  DOI 请求异常: {e}")

        return None, diag

    def _handle_sciencedirect(self, linkinghub_url: str, doi: str, client: httpx.Client, pdf_path: Path):
        """
        处理 Elsevier ScienceDirect 论文下载。
        linkinghub.elsevier.com 是 JS 跳转页，httpx 无法跟随。
        从 URL 中提取 PII，构造 ScienceDirect 文章页 URL 后抓取 PDF。
        """
        diag = []

        # 从 URL 提取 PII: /pii/S2542435119301576
        m = re.search(r'/pii/([A-Z0-9]+)', linkinghub_url)
        if not m:
            # 也可能直接在 sciencedirect.com URL 中
            m = re.search(r'/pii/([A-Z0-9]+)', linkinghub_url)
        if not m:
            diag.append("  无法从 URL 提取 PII")
            return None, diag

        pii = m.group(1)
        diag.append(f"  PII: {pii}")

        # 构造 ScienceDirect 文章页 URL
        sd_article_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
        diag.append(f"  请求 ScienceDirect 文章页: {sd_article_url[:120]}")

        try:
            # 模拟浏览器请求头，带 DOI 页作为 Referer
            resp = client.get(sd_article_url, headers={
                "User-Agent": self._UA,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                "Referer": f"https://doi.org/{doi}",
            })
            diag.append(f"  SD 文章页: HTTP {resp.status_code}")

            if resp.status_code == 403:
                diag.append("  SD 返回 403，可能被反爬 — 建议用 Selenium 重试")
                return None, diag

            if resp.status_code != 200:
                return None, diag

            final_url = str(resp.url)

            # 提取 citation_pdf_url
            pdf_url = self._extract_pdf_from_html(resp.text, final_url)

            # ScienceDirect 专用：也尝试从页面构造 PDF URL
            if not pdf_url:
                # 模式: /science/article/pii/{pii}/pdfft?...
                m2 = re.search(
                    r'href=["\']([^"\']*/science/article/pii/' + re.escape(pii) + r'/[^"\']*pdf[^"\']*)["\']',
                    resp.text, re.IGNORECASE
                )
                if m2:
                    pdf_url = urljoin(final_url, m2.group(1))
                    diag.append(f"  SD 构造 PDF URL: {pdf_url[:150]}")

            if not pdf_url:
                diag.append("  ScienceDirect 页面未找到 PDF 链接")
                if "citation_pdf_url" in resp.text:
                    diag.append("  (HTML 含 citation_pdf_url 但提取失败)")
                return None, diag

            diag.append(f"  PDF URL: {pdf_url[:150]}")

            # 下载 PDF
            resp2 = client.get(pdf_url, headers={
                "User-Agent": self._UA,
                "Referer": sd_article_url,
            })
            ct2 = resp2.headers.get("content-type", "")
            diag.append(f"  PDF 请求: HTTP {resp2.status_code}, ct={ct2[:60]}")

            if resp2.status_code == 200 and self._is_pdf(resp2):
                pdf_path.write_bytes(resp2.content)
                diag.append(f"  PDF 下载成功 ({len(resp2.content)} bytes)")
                return pdf_path.name, diag
            elif resp2.status_code in (401, 403):
                diag.append(f"  PDF 被拒绝 (HTTP {resp2.status_code}) — 可能需额外认证")
            elif resp2.status_code == 302:
                diag.append(f"  PDF 请求被重定向到: {resp2.headers.get('location', '?')[:120]}")
            else:
                diag.append(f"  PDF 请求失败: HTTP {resp2.status_code}")

        except Exception as e:
            diag.append(f"  ScienceDirect 处理异常: {e}")

        return None, diag

    def _download_via_unpaywall(self, doi: str, pdf_path: Path) -> Optional[str]:
        """通过 Unpaywall API 查找开放获取 PDF"""
        try:
            url = f"https://api.unpaywall.org/v2/{doi}?email=search-papers@cc-cj"
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers={"User-Agent": self._UA})
                if resp.status_code != 200:
                    return None
                data = resp.json()
                oa_pdf = (data.get("best_oa_location") or {}).get("url_for_pdf")
                if not oa_pdf:
                    return None
                return self._download_url(oa_pdf, pdf_path)
        except Exception:
            return None

    @staticmethod
    def _is_pdf(resp) -> bool:
        """判断 HTTP 响应是否为 PDF"""
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct:
            return True
        if resp.content[:4] == b"%PDF":
            return True
        return False

    def _extract_pdf_from_html(self, html: str, page_url: str) -> Optional[str]:
        """
        从出版商 HTML 页面提取 PDF 下载链接。

        按优先级尝试多种模式:
        1. <meta name="citation_pdf_url"> — CrossRef 标准，Elsevier/Springer/Wiley/ACS 等均支持
        2. <meta name="pdf-url"> / <meta name="fulltext_pdf">
        3. <a href="...pdf"> 链接
        4. URL 路径中包含 /pdf/ 的链接
        """
        # 模式 1: citation_pdf_url meta 标签（最可靠）
        for pattern in [
            r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
            r'<meta[^>]*citation_pdf_url[^>]*content=["\']([^"\']+)["\']',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return m.group(1)

        # 模式 2: 其他 PDF 相关 meta 标签
        for pattern in [
            r'<meta\s+name=["\']pdf-url["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+name=["\']fulltext_pdf["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+property=["\']og:url["\']\s+content=["\']([^"\']+\.pdf)["\']',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return m.group(1)

        # 模式 3: <a href="...">PDF</a> 显式下载链接
        for pattern in [
            r'<a[^>]*href=["\']([^"\']*\.pdf)["\'][^>]*>',
            r'<a[^>]*href=["\']([^"\']*/pdf/[^"\']+)["\']',
            r'<a[^>]*href=["\']([^"\']*download[^"\']*pdf[^"\']*)["\']',
        ]:
            for m in re.finditer(pattern, html, re.IGNORECASE):
                candidate = urljoin(page_url, m.group(1))
                if self._url_looks_like_pdf(candidate):
                    return candidate

        # 模式 4: 页面 URL 路径替换（如 /doi/abs/ → /doi/pdf/）
        for check, replace in [
            ("/doi/abs/", "/doi/pdf/"),
            ("/doi/full/", "/doi/pdf/"),
            ("/article/", "/article/pdffull/"),
            ("/science/article/", "/science/article/pdffull/"),
        ]:
            if check in page_url:
                candidate = page_url.replace(check, replace)
                if self._url_looks_like_pdf(candidate):
                    return candidate
            # 也试试 body 里的链接
            for m in re.finditer(
                r'href=["\']([^"\']*' + re.escape(check) + r'[^"\']*)["\']',
                html, re.IGNORECASE
            ):
                raw = m.group(1)
                candidate = urljoin(page_url, re.sub(check, replace, raw, flags=re.IGNORECASE))
                if self._url_looks_like_pdf(candidate):
                    return candidate

        return None

    @staticmethod
    def _url_looks_like_pdf(url: str) -> bool:
        """判断 URL 是否可能是 PDF 链接"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(".pdf"):
            return True
        if "/pdf/" in path:
            return True
        if "download" in path and "pdf" in path:
            return True
        return False

    # ── Selenium 下载（校园网 DOI 论文）──────

    def _download_via_selenium_batch(self, papers: list) -> dict:
        """
        使用 Selenium + Firefox 批量下载论文 PDF。
        真实浏览器可跟随 JS 跳转、复用校园网/VPN 登录态。

        papers: [(paper, filename), ...]
        返回 {filename: pdf_name_or_None}
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.firefox.service import Service
            from webdriver_manager.firefox import GeckoDriverManager
        except ImportError:
            print("  ⚠ selenium 未安装，跳过 Selenium 下载。")
            print("     安装: pip install selenium webdriver-manager")
            return {}

        RAW_DIR.mkdir(parents=True, exist_ok=True)

        # snap Firefox 无法访问 /tmp，profile 必须放在 home 目录
        profile_dir = Path.home() / ".mozilla" / "selenium_download"
        profile_dir.mkdir(parents=True, exist_ok=True)

        fx_options = Options()
        # fx_options.add_argument("--headless")

        fx_profile = webdriver.FirefoxProfile(profile_directory=str(profile_dir))
        fx_profile.set_preference("browser.download.folderList", 2)
        fx_profile.set_preference("browser.download.dir", str(RAW_DIR.resolve()))
        fx_profile.set_preference("browser.download.useDownloadDir", True)
        fx_profile.set_preference("browser.helperApps.neverAsk.saveToDisk",
                                  "application/pdf,application/octet-stream")
        fx_profile.set_preference("pdfjs.disabled", True)
        fx_options.profile = fx_profile

        # 优先用系统 geckodriver
        driver = None
        for gecko_path in ("/usr/bin/geckodriver", "/usr/local/bin/geckodriver"):
            if os.path.exists(gecko_path):
                try:
                    service = Service(executable_path=gecko_path)
                    driver = webdriver.Firefox(service=service, options=fx_options)
                    break
                except Exception:
                    pass

        if driver is None:
            try:
                service = Service(GeckoDriverManager().install())
                driver = webdriver.Firefox(service=service, options=fx_options)
            except Exception as e:
                print(f"  ⚠ 无法启动 Firefox: {e}")
                print("     国内用户请用 apt 安装: sudo apt install firefox-geckodriver")
                return {}

        results = {}

        try:
            for paper, filename in papers:
                pdf_name = filename.replace(".md", ".pdf")
                pdf_path = RAW_DIR / pdf_name

                if pdf_path.exists() and pdf_path.stat().st_size > 0:
                    print(f"  ✅ {filename}: PDF 已存在，跳过")
                    results[filename] = pdf_name
                    continue

                url = self._pick_download_url(paper)
                if not url:
                    print(f"  ❌ {filename}: 无可访问 URL")
                    results[filename] = None
                    continue

                print(f"  🌐 {filename}: 打开 {url[:100]}...")
                try:
                    driver.get(url)
                    time.sleep(8)

                    current_url = driver.current_url
                    print(f"     当前页面: {current_url[:120]}")

                    clicked = self._selenium_click_pdf(driver)
                    if clicked:
                        print("     PDF 按钮已点击，等待下载...")
                        time.sleep(12)
                        downloaded = self._find_downloaded_pdf(RAW_DIR, pdf_name)
                        if downloaded:
                            print(f"     ✅ PDF 下载成功: {downloaded}")
                        else:
                            print("     ❌ 未检测到下载文件")
                        results[filename] = downloaded
                    else:
                        print("     ❌ 页面中未找到 PDF 按钮/链接")
                        results[filename] = None
                except Exception as e:
                    print(f"  ⚠ Selenium [{filename}]: {e}")
                    results[filename] = None
        finally:
            driver.quit()

        return results

    @staticmethod
    def _pick_download_url(paper: Paper) -> str:
        """为论文选择最合适的浏览器访问 URL"""
        if paper.url and "doi.org" not in paper.url:
            return paper.url
        if paper.doi:
            return f"https://doi.org/{paper.doi}"
        return paper.url or ""

    @staticmethod
    def _selenium_click_pdf(driver) -> bool:
        """在已加载的页面中寻找并点击 PDF 按钮/链接"""
        from selenium.webdriver.common.by import By

        keywords = [
            "PDF", "Download PDF", "View PDF", "Full Text PDF",
            "Article PDF", "Download Article", "下载PDF", "PDF下载",
        ]

        # 1. 按文本匹配
        for key in keywords:
            elements = driver.find_elements(
                By.XPATH, f"//*[contains(text(), '{key}')]"
            )
            for el in elements:
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", el)
                    time.sleep(0.5)
                    el.click()
                    return True
                except Exception:
                    pass

        # 2. 按 aria-label / title 匹配
        for key in ["pdf", "download"]:
            elements = driver.find_elements(
                By.XPATH, f"//*[contains(translate(@aria-label,'PDF','pdf'),'{key}') or contains(translate(@title,'PDF','pdf'),'{key}')]"
            )
            for el in elements:
                try:
                    el.click()
                    return True
                except Exception:
                    pass

        # 3. 直接找 href 含 .pdf 的链接
        links = driver.find_elements(By.TAG_NAME, "a")
        for a in links:
            href = a.get_attribute("href") or ""
            if ".pdf" in href.lower():
                try:
                    driver.get(href)
                    return True
                except Exception:
                    pass

        return False

    @staticmethod
    def _find_downloaded_pdf(download_dir: Path, expected_name: str) -> Optional[str]:
        """在下载目录找到刚下载的 PDF 并重命名为预期文件名"""
        # 找最近修改的 .pdf 或 .crdownload（下载中）
        candidates = []
        for f in download_dir.iterdir():
            if f.suffix.lower() in (".pdf", ".crdownload"):
                candidates.append(f)

        if not candidates:
            return None

        candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        newest = candidates[0]

        # 如果还在下载中，等一会
        if newest.suffix == ".crdownload":
            for _ in range(15):
                time.sleep(2)
                if not newest.exists():
                    break
            # 重新找 pdf
            for f in download_dir.iterdir():
                if f.suffix.lower() == ".pdf":
                    candidates.append(f)
            candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            if candidates and candidates[0].suffix == ".pdf":
                newest = candidates[0]
            else:
                return None

        # 如果文件名不同，重命名
        target = download_dir / expected_name
        if newest != target:
            if target.exists():
                target.unlink()
            newest.rename(target)

        return expected_name

    # ── 重试失败下载（Selenium 兜底）──────────

    def retry_failed_downloads(self, results: list[dict]) -> int:
        """
        对 PDF 下载失败的论文，用 Selenium 批量重试。
        返回成功下载数。
        """
        failed = []
        for r in results:
            if r.get("status") == "created" and not r.get("pdf"):
                paper_data = r.get("paper", {})
                paper = Paper(
                    title=paper_data.get("title", ""),
                    authors=[],
                    doi=paper_data.get("doi", ""),
                    url=paper_data.get("url", ""),
                    source=paper_data.get("source", ""),
                )
                url = self._pick_download_url(paper)
                filename = r["filename"]
                print(f"  Selenium 待下载: {filename}")
                print(f"    DOI: {paper_data.get('doi', '无')}")
                print(f"    URL: {url}")
                failed.append((paper, filename))

        if not failed:
            return 0

        sys.stdout.flush()
        print(f"\n🖥  启动 Selenium Firefox 浏览器重试 {len(failed)} 篇...")
        print("   (浏览器窗口会打开，请勿关闭，完成后自动退出)")
        sys.stdout.flush()

        results_map = self._download_via_selenium_batch(failed)

        # 打印结果
        for filename, pdf_name in results_map.items():
            if pdf_name:
                print(f"  ✅ {filename} → PDF 下载成功")
            else:
                print(f"  ❌ {filename} → 下载失败")

        count = 0
        for r in results:
            filename = r.get("filename", "")
            if filename in results_map and results_map[filename]:
                r["pdf"] = results_map[filename]
                r["pdf_path"] = str(RAW_DIR / results_map[filename])
                count += 1

        return count

    # ── 元数据桩生成 ──────────────────────────

    def _build_metadata_stub(self, paper: Paper, pdf_name: str, topic: str) -> str:
        """
        生成元数据桩 .md 文件。
        只包含 frontmatter + 文献信息表 + 下载链接。
        详细分析（核心研究问题、模型框架等）由 wiki agent 补充。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        doi_url = f"https://doi.org/{paper.doi}" if paper.doi else ""
        authors_fm = ", ".join(paper.authors[:8])
        title_display = f"{paper.title} ({paper.year})" if paper.year else paper.title

        # 标签推断
        tags = ["#literature"]
        v = (paper.venue or "").lower()
        t = (paper.title or "").lower()
        a = (paper.abstract or "").lower()
        text_all = f"{v} {t} {a}"
        if any(k in text_all for k in ["battery", "electrochem", "li-ion", "solid-state"]):
            tags.append("#electrochemistry")
        if any(k in text_all for k in ["fracture", "mechanics", "stress", "deformation", "crack"]):
            tags.append("#solid-mechanics")
        if any(k in text_all for k in ["phase-field", "phase field"]):
            tags.append("#phase-field")
        if any(k in text_all for k in ["simulation", "modeling", "fem", "finite element"]):
            tags.append("#simulation")
        if any(k in text_all for k in ["experiment", "characterization", "measure"]):
            tags.append("#experimental")
        if any(k in text_all for k in ["review", "survey", "progress", "overview"]):
            tags.append("#review")

        # 推断研究类型
        if any(k in text_all for k in ["review", "survey", "progress", "overview"]):
            research_type = "review"
        elif any(k in text_all for k in ["simulation", "modeling", "fem", "finite element", "phase-field"]):
            research_type = "simulation"
        elif any(k in text_all for k in ["experiment", "characterization", "measure", "synthesis"]):
            research_type = "experimental"
        else:
            research_type = "theoretical"

        # PDF 下载链接块
        pdf_block = ""
        if pdf_name:
            pdf_block = f"""> [:arrow_down: 下载 PDF](../raw/literature/{pdf_name})

---
"""
        else:
            pdf_block = """> :warning: PDF 下载失败，请手动获取。DOI: {doi_url or '无'}

---
"""

        lines = [
            "---",
            f"title: {paper.title}",
            "type: source",
            f"tags: [{', '.join(tags)}]",
            f"created: {today}",
            f"updated: {today}",
            f"authors: [{authors_fm}]",
            f"year: {paper.year or ''}",
            f"journal: {paper.venue or ''}",
            f"doi: {doi_url}",
            f"research_type: {research_type}",
            "sources: []",
            "related: []",
            "---",
            "",
            pdf_block,
            f"# {title_display}",
            "",
            "## 文献信息",
            "",
            f"| 属性 | 值 |",
            f"|------|-----|",
            f"| **作者** | {paper.authors_str} |",
            f"| **年份** | {paper.year or '未知'} |",
            f"| **期刊** | {paper.venue or '未知'} |",
            f"| **DOI** | {doi_url or '无'} |",
            f"| **引用数** | {paper.citation_count or '未知'} |",
            f"| **来源** | {paper.source} |",
            f"| **arXiv ID** | {paper.arxiv_id or '无'} |",
            "",
            "## 摘要",
            "",
            paper.abstract[:800] + ("..." if len(paper.abstract or "") > 800 else "") if paper.abstract else "_（暂无摘要）_",
            "",
            "---",
            "",
            "## 研究目标",
            "",
            "_（待 wiki agent 补充 — 读取 PDF 后填写核心研究问题）_",
            "",
            "## 关键方法",
            "",
            "_（待 wiki agent 补充 — 读取 PDF 后填写方法/技术）_",
            "",
            "## 主要发现/结论",
            "",
            "_（待 wiki agent 补充 — 读取 PDF 后填写关键发现）_",
            "",
            "### 多物理场耦合相关",
            "",
            "_（待填充：本文涉及的力-热-电-化学耦合机制）_",
            "",
            "## 对你研究的价值",
            "",
            "_（待 wiki agent 补充 — 分析对固态电池多物理场研究的参考价值）_",
            "",
            "## 数据可用性",
            "",
            "- [ ] 原始数据",
            "- [ ] 仿真模型",
            "- [ ] 代码开源",
            "",
            "## 相关实体",
            "",
            "_（待 wiki agent 补充 — 关联的实体页面 [[entity-name]]）_",
            "",
            "## 相关概念",
            "",
            "_（待 wiki agent 补充 — 关联的概念页面 [[concept-name]]）_",
            "",
            "## 备注",
            "",
            f"- URL: {paper.url}",
            f"- 搜索主题: {topic if topic else '无'}",
            "- 摄入时间: " + today,
        ]

        return "\n".join(lines) + "\n"

    # ── 重复检测 ──────────────────────────────

    def _load_existing_sources(self) -> dict:
        """扫描已有 source 文件，建立索引"""
        if self._existing_sources is not None:
            return self._existing_sources

        sources = {"by_doi": {}, "by_title": {}, "filenames": set()}
        if not SOURCES_DIR.exists():
            self._existing_sources = sources
            return sources

        for f in SOURCES_DIR.iterdir():
            if not f.suffix == ".md":
                continue
            sources["filenames"].add(f.name)
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue

            fm = self._parse_frontmatter(text)
            doi = fm.get("doi", "").strip().lower()
            title = fm.get("title", "").strip().lower()
            if doi:
                sources["by_doi"][doi] = f.name
            if title:
                sources["by_title"][title] = f.name

        self._existing_sources = sources
        return sources

    def _parse_frontmatter(self, text: str) -> dict:
        """解析 YAML frontmatter"""
        if not text.startswith("---"):
            return {}
        end = text.find("---", 3)
        if end == -1:
            return {}
        fm_text = text[3:end]
        result = {}
        for line in fm_text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip()
        return result

    def _check_duplicate(self, paper: Paper) -> dict:
        """三重重复检测: DOI 精确匹配 → 标题精确匹配 → 标题模糊匹配(≥85%)"""
        sources = self._load_existing_sources()

        if paper.doi:
            doi_key = paper.doi.strip().lower()
            if doi_key in sources["by_doi"]:
                return {"is_dup": True, "reason": f"DOI 已存在 ({paper.doi})",
                        "existing_path": sources["by_doi"][doi_key]}

        title_key = paper.title.strip().lower()
        if title_key in sources["by_title"]:
            return {"is_dup": True, "reason": "标题完全匹配已存在",
                    "existing_path": sources["by_title"][title_key]}
        for existing_title, fn in sources["by_title"].items():
            if SequenceMatcher(None, title_key, existing_title).ratio() >= 0.85:
                return {"is_dup": True, "reason": f"标题相似度≥85% 匹配: {fn}",
                        "existing_path": fn}

        return {"is_dup": False}

    # ── 文件名生成 ────────────────────────────

    def _resolve_filename(self, abbrev: str, year: int, paper: Paper) -> str:
        """解决文件名冲突"""
        sources = self._load_existing_sources()
        base = f"{abbrev}-{year}" if abbrev else f"paper-{year}"
        candidate = f"{base}.md"

        if candidate not in sources["filenames"] and not (SOURCES_DIR / candidate).exists():
            return candidate

        existing_path = SOURCES_DIR / candidate
        if existing_path.exists():
            existing_text = existing_path.read_text(encoding="utf-8")
            fm = self._parse_frontmatter(existing_text)
            if paper.doi and fm.get("doi", "").strip().lower() == paper.doi.strip().lower():
                return candidate

        for i in range(2, 100):
            candidate = f"{base}-{i}.md"
            if candidate not in sources["filenames"] and not (SOURCES_DIR / candidate).exists():
                return candidate

        import hashlib
        h = hashlib.md5(paper.title.encode()).hexdigest()[:8]
        return f"{base}-{h}.md"

    # ── Wiki 元数据 ────────────────────────────

    def _load_concepts(self) -> set:
        if self._existing_concepts is not None:
            return self._existing_concepts
        concepts = set()
        if CONCEPTS_DIR.exists():
            for f in CONCEPTS_DIR.rglob("*.md"):
                concepts.add(f.stem)
        self._existing_concepts = concepts
        return concepts

    def _load_entities(self) -> set:
        if self._existing_entities is not None:
            return self._existing_entities
        entities = set()
        if ENTITIES_DIR.exists():
            for f in ENTITIES_DIR.rglob("*.md"):
                entities.add(f.stem)
        self._existing_entities = entities
        return entities

    # ── 日志 ──────────────────────────────────

    def _append_log(self, filename: str, paper: Paper, pdf_name: str = ""):
        """追加操作记录到 log.md"""
        today = datetime.now().strftime("%Y-%m-%d")
        pdf_info = f"\n- PDF: [[../raw/literature/{pdf_name}]]" if pdf_name else "\n- PDF: 下载失败"
        entry = f"""
## [{today}] ingest | {paper.title[:80]} → [[{filename.replace('.md', '')}]]{pdf_info}

- 作者: {paper.authors_str}
- 年份: {paper.year or '未知'}
- 期刊: {paper.venue or '未知'}
- DOI: {paper.doi or '无'}
- 来源: {paper.source}
"""
        if LOG_PATH.exists():
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)


# ─────────────────────────────────────────────
#  Wiki Agent 启动标记
# ─────────────────────────────────────────────

def build_agent_prompt(pending: list[dict], topic: str = "") -> str:
    """
    根据待处理论文列表，生成 wiki agent 的启动 prompt。
    wiki agent 需要读取 wiki/CLAUDE.md 并严格遵循其工作流。
    """
    if not pending:
        return ""

    paper_lines = []
    for item in pending:
        p = item.get("paper", {})
        paper_lines.append(f"""
### [{item['page_id']}]
- **标题**: {p.get('title', '')}
- **作者**: {p.get('authors', '')}
- **年份**: {p.get('year', '')} | **期刊**: {p.get('journal', '')}
- **DOI**: {p.get('doi', '')}
- **摘要**: {(p.get('abstract', '') or '')[:300]}
- **PDF**: {item.get('pdf_path', '无')}
- **元数据桩**: {item.get('path', '')}
""")

    papers_section = "\n".join(paper_lines)

    wiki_claude_md = WIKI_CLAUDE_MD if WIKI_CLAUDE_MD.exists() else Path("wiki/CLAUDE.md")
    return f"""你是一个学术 Wiki 维护 agent。请严格遵循 `{wiki_claude_md}` 中的工作流程，处理以下 {len(pending)} 篇论文。

## 搜索主题
{topic if topic else '未指定'}

## 待处理论文
{papers_section}

## 工作流程（来自 wiki/CLAUDE.md）

### Step 1: 读取 PDF，判断文献类型
- 综述类（含 review/survey/progress 关键词）→ 读取全部或前 12 页
- 研究类 → 读取前 8-10 页
- 如果 PDF 下载失败，基于摘要和元数据分析

### Step 2: 完善 source 摘要页
当前元数据桩已包含 frontmatter 和基本信息。你需要：
- 替换占位符 `_（待 wiki agent 补充...）_` 为实际分析内容
- 必须包含：核心研究问题、模型框架、关键发现、创新点、对你研究的价值
- wiki 链接仅放在「相关实体」「相关概念」段落及 frontmatter related: 字段
- 禁止正文中内联 wiki 链接轰炸

### Step 3: 更新相关实体/概念页面
- 将新 source ID 添加到所有相关实体页的 sources:/related: 字段
- 将新 source ID 添加到所有相关概念页的 sources:/related: 字段
- 确保被引用页面有回链（双向链接）
- related: 字段使用 `[[...]], [[...]]` 双括号格式，不得使用 YAML 数组

### Step 4: 更新 wiki/index.md
- 在正确的分类表中添加新文献行

### Step 5: 在 wiki/log.md 追加操作记录

### Post-Ingest 检查清单
1. 断链检查：`[[link]]` 指向的页面是否存在
2. 括号完整性：frontmatter 中 `[[` 和 `]]` 数量相等
3. 双向链接：新 source 链接的 entity/concept 页面是否有回链
4. 格式一致性：related: 和 sources: 字段使用 `[[...]], [[...]]` 格式
5. 重复文件检查：同一页面名不存在于多个目录"""


def print_agent_ready_summary(pending: list[dict]):
    """打印简要摘要，告知用户 wiki agent 可以启动"""
    if not pending:
        print("\n✅ 没有待 wiki agent 处理的论文")
        return

    print(f"\n{'='*60}")
    print(f"  Wiki Bridge 完成 — {len(pending)} 篇论文元数据桩已就绪")
    print(f"{'='*60}")
    for item in pending:
        pdf_status = "PDF已下载" if item.get("pdf") else "PDF下载失败"
        print(f"  📄 {item['filename']} ({pdf_status})")
    print(f"\n  → wiki agent 现在可以按 CLAUDE.md 工作流处理以上论文")
    print(f"  → Agent prompt 已生成，调用 build_agent_prompt() 获取")
    print(f"{'='*60}\n")
