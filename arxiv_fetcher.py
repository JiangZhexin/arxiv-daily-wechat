# -*- coding: utf-8 -*-
"""
arxiv_fetcher.py
从 arXiv API 抓取指定分类（math.DG / math.GN / math.GT 等）最近发布的新论文。

arXiv API 文档: https://info.arxiv.org/help/api/user-manual.html
本模块只依赖标准库 xml.etree 和 requests，无其他第三方依赖。
"""
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

ARXIV_API_URL = "https://export.arxiv.org/api/query"

# arXiv Atom 源用到的 XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _parse_published(raw: str):
    """解析 arXiv 时间字符串，如 '2026-08-24T02:35:12Z'，转成 UTC datetime。"""
    try:
        dt = datetime.strptime(raw.strip(), "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_new_papers(
    categories,
    hours_back: int = 30,
    max_results: int = 300,
    retries: int = 3,
):
    """
    抓取最近 hours_back 小时内提交的新论文。

    参数:
        categories: 分类列表，如 ["math.DG", "math.GN", "math.GT"]
        hours_back: 只看最近多少小时内发布的论文。
                    默认 30 小时：每天固定时间跑一次时，正好覆盖最近一次发布，
                    不会重复推送前一天的论文（arXiv 周末不发布，周一早上为 0 篇属正常）。
        max_results: 最多向 API 拉取多少条（再按时间过滤）
        retries: API 请求失败时的重试次数

    返回:
        论文列表，每项为 dict:
            id, url, title, summary, published(datetime), primary, categories, authors
        按发布时间从新到旧排序，已按 id 去重。
    """
    query = " OR ".join(f"cat:{c}" for c in categories)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    # arXiv 官方要求提供 User-Agent，否则可能被限流/拒绝
    headers = {"User-Agent": "arxiv-daily-wechat/1.0 (arXiv daily digest; contact: github.com/JiangZhexin/arxiv-daily-wechat)"}

    # 请求 arXiv API，失败自动重试
    resp = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"arXiv API 请求失败: {exc}") from exc
            time.sleep(5 * (attempt + 1))

    # 诊断日志：便于排查"抓到 0 篇"问题
    print(f"  [调试] arXiv API 状态={resp.status_code}, 响应 {len(resp.text)} 字符, 窗口={hours_back}h")
    if "opensearch:totalResults" not in resp.text:
        print(f"  [警告] arXiv 返回内容异常（可能被限流）: {resp.text[:300]}")

    root = ET.fromstring(resp.text)

    papers = []
    seen_ids = set()
    for entry in root.findall("atom:entry", NS):
        paper_id = entry.findtext("atom:id", default="", namespaces=NS)
        # 取 id 中 /abs/ 之后的部分，如 "2508.12345"
        short_id = paper_id.split("/abs/")[-1].strip()
        if not short_id or short_id in seen_ids:
            continue

        published = _parse_published(entry.findtext("atom:published", default="", namespaces=NS))
        if published is None or published < cutoff:
            continue

        title = " ".join(entry.findtext("atom:title", default="", namespaces=NS).split())
        summary = " ".join(entry.findtext("atom:summary", default="", namespaces=NS).split())

        authors = [
            a.findtext("atom:name", default="", namespaces=NS)
            for a in entry.findall("atom:author", NS)
            if a.findtext("atom:name", default="", namespaces=NS)
        ]

        cat_nodes = entry.findall("atom:category", NS)
        all_categories = [c.get("term") for c in cat_nodes if c.get("term")]

        pc = entry.find("arxiv:primary_category", NS)
        primary = pc.get("term") if pc is not None else (all_categories[0] if all_categories else "")

        seen_ids.add(short_id)
        papers.append(
            {
                "id": short_id,
                "url": f"https://arxiv.org/abs/{short_id}",
                "title": title,
                "summary": summary,
                "published": published,
                "primary": primary,
                "categories": all_categories,
                "authors": authors,
            }
        )

    papers.sort(key=lambda p: p["published"], reverse=True)
    return papers


if __name__ == "__main__":
    # 本地自测：python arxiv_fetcher.py
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    result = fetch_new_papers(["math.DG", "math.GN", "math.GT"], hours_back=72)
    print(f"抓到 {len(result)} 篇论文：")
    for p in result[:10]:
        print(f"  [{p['primary']}] {p['id']} {p['title'][:60]} ({p['published']:%Y-%m-%d})")
