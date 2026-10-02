# -*- coding: utf-8 -*-
"""
filters.py —— 按「关键词」和「作者」挑出你关心的论文。

用途（不影响原有的每日全量推送）：
  1. 微信里额外单独发一条「⭐ 关注命中」提醒
  2. 网页上给命中的论文加星标 + 命中原因

规则：
  - 关键词：在标题 / 摘要里做不区分大小写的子串匹配。
            多词短语（如 "Ricci flow"）会当作整体匹配；想放宽就写单个词。
  - 作者：  只在指定分区（author_categories）里匹配，其他分区完全不受作者条件影响；
            名字不区分大小写、忽略音标（写 Lopez 也能匹配 López），支持只写姓氏。
  - 组合：  logic = "or"（默认，关键词或作者任一命中即可）或 "and"（两类都必须命中）。
            只配置了一类的条件时，and 会退化为「只看该类条件」。
"""
import unicodedata

# 关键词匹配范围
SCOPE_TITLE = "title"           # 只匹配标题
SCOPE_TITLE_ABSTRACT = "title_abstract"  # 标题 + 摘要（默认）
SCOPE_ALL = "all"               # 标题 + 摘要 + 作者 + 分区等全部元数据

VALID_SCOPES = (SCOPE_TITLE, SCOPE_TITLE_ABSTRACT, SCOPE_ALL)
VALID_LOGIC = ("or", "and")


def normalize(text: str) -> str:
    """转小写并去掉音标符号，便于跨语言/跨拼写匹配。"""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _keyword_text(paper, scope):
    """取出用于关键词匹配的文本。"""
    if scope == SCOPE_TITLE:
        return paper.get("title") or ""
    if scope == SCOPE_ALL:
        parts = [
            paper.get("title") or "",
            paper.get("summary") or "",
            " ".join(paper.get("categories") or []),
            " ".join(paper.get("authors") or []),
            paper.get("primary") or "",
        ]
        return " ".join(p for p in parts if p)
    return f"{paper.get('title') or ''} {paper.get('summary') or ''}"


def match_keywords(paper, keywords, scope=SCOPE_TITLE_ABSTRACT):
    """返回命中的关键词列表（没命中就是空列表）。"""
    if not keywords:
        return []
    haystack = normalize(_keyword_text(paper, scope))
    if not haystack:
        return []
    return [kw for kw in keywords if normalize(kw) and normalize(kw) in haystack]


def match_authors(paper, authors, author_categories=None):
    """返回命中的作者查询词列表。

    author_categories 非空时，只有属于这些分区的论文才参与作者匹配
    （其他分区不受作者条件影响）。
    """
    if not authors:
        return []
    if author_categories:
        cats = set(paper.get("categories") or [])
        if paper.get("primary"):
            cats.add(paper["primary"])
        if not (cats & set(author_categories)):
            return []

    paper_authors = [normalize(a) for a in (paper.get("authors") or []) if a]
    if not paper_authors:
        return []
    hits = []
    for want in authors:
        w = normalize(want)
        if w and any(w in pa for pa in paper_authors):
            hits.append(want)
    return hits


def match_papers(papers, config):
    """挑出命中的论文。

    config: {
        "keywords": ["Calabi-Yau", ...],
        "authors": ["Shing-Tung Yau", ...],
        "author_categories": ["math.DG"],     # 作者条件只在这些分区里生效
        "scope": "title_abstract",            # title / title_abstract / all
        "logic": "or",                        # or / and
    }

    返回: [(paper, {"keywords": [...], "authors": [...]}), ...]
    """
    config = config or {}
    keywords = config.get("keywords") or []
    authors = config.get("authors") or []
    author_categories = config.get("author_categories") or []
    scope = config.get("scope") or SCOPE_TITLE_ABSTRACT
    if scope not in VALID_SCOPES:
        scope = SCOPE_TITLE_ABSTRACT
    logic = (config.get("logic") or "or").lower()
    if logic not in VALID_LOGIC:
        logic = "or"

    results = []
    for paper in papers:
        kw_hits = match_keywords(paper, keywords, scope)
        au_hits = match_authors(paper, authors, author_categories)

        conditions = []
        if keywords:
            conditions.append(bool(kw_hits))
        if authors:
            conditions.append(bool(au_hits))
        if not conditions:
            continue
        hit = all(conditions) if logic == "and" else any(conditions)
        if hit:
            results.append((paper, {"keywords": kw_hits, "authors": au_hits}))
    return results


def describe_hit(hit, category_label=None):
    """把命中原因整理成一行可读文本，如「关键词 Calabi-Yau · 作者 Yau」。"""
    bits = []
    if hit.get("keywords"):
        bits.append("关键词 " + " / ".join(hit["keywords"]))
    if hit.get("authors"):
        bits.append("作者 " + " / ".join(hit["authors"]))
    if category_label:
        bits.append(category_label)
    return " · ".join(bits)
