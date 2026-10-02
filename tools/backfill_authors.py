# -*- coding: utf-8 -*-
"""
tools/backfill_authors.py
给「加作者行之前」生成的历史页面（pages/daily-*.html）补上作者。

作者通过 arXiv API 按论文 id 批量查询（每批最多 100 个 id，批间休眠 3 秒）。

用法：
    python tools/backfill_authors.py              # 处理 pages/ 目录
    python tools/backfill_authors.py 某个目录      # 处理指定目录
"""
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arxiv_fetcher import _clean_author_name

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
HEADERS = {"User-Agent": "arxiv-daily-wechat/1.0 (author backfill)"}
AUTHORS_CSS = ".authors { color: #555; font-size: 0.88em; margin: 3px 0 5px; }"

LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
ID_RE = re.compile(r'arxiv\.org/abs/([^"]+)"')
EN_TITLE_RE = re.compile(r'(<div class="en-title">.*?</div>)', re.DOTALL)


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _norm_id(raw):
    """去掉版本号：2608.12345v2 → 2608.12345"""
    return re.sub(r"v\d+$", "", raw.strip())


def _ids_of_page(html):
    """按出现顺序取出该页面所有论文 id。"""
    ids = []
    for m in LI_RE.finditer(html):
        hit = ID_RE.search(m.group(1))
        if hit:
            pid = _norm_id(hit.group(1))
            if pid not in ids:
                ids.append(pid)
    return ids


def fetch_authors(ids, cache=None):
    """批量查询作者，返回 {id: [作者...]}；cache 可跨文件复用。"""
    cache = cache if cache is not None else {}
    todo = [i for i in ids if i not in cache]
    for i in range(0, len(todo), 100):
        batch = todo[i : i + 100]
        resp = requests.get(
            API,
            params={"id_list": ",".join(batch), "max_results": len(batch)},
            headers=HEADERS,
            timeout=60,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        for entry in root.iter(ATOM + "entry"):
            pid = _norm_id((entry.findtext(ATOM + "id", default="") or "").rsplit("/abs/", 1)[-1])
            names = [
                _clean_author_name(a.findtext(ATOM + "name", default="") or "")
                for a in entry.findall(ATOM + "author")
            ]
            cache[pid] = [n for n in names if n]
        for pid in batch:
            cache.setdefault(pid, [])
        print(f"  [API] 已查询 {len(batch)} 篇（累计 {len(cache)} 篇）")
        if i + 100 < len(todo):
            time.sleep(3)
    return cache


def patch_html(html, authors_map):
    """在每篇的英文标题后插入作者行；返回 (新 html, 统计)。"""
    if ".authors {" not in html:
        html = html.replace("</style>", AUTHORS_CSS + "\n</style>", 1)

    stats = {"filled": 0, "skipped": 0, "missing": 0}

    def _sub_li(m):
        li = m.group(1)
        if 'class="authors"' in li:
            stats["skipped"] += 1
            return m.group(0)
        hit = ID_RE.search(li)
        names = authors_map.get(_norm_id(hit.group(1))) if hit else None
        if not names:
            stats["missing"] += 1
            return m.group(0)
        line = '<div class="authors">👥 ' + _escape(", ".join(names)) + "</div>"
        new_li, n = EN_TITLE_RE.subn(lambda mm: mm.group(1) + line, li, count=1)
        if not n:
            stats["missing"] += 1
            return m.group(0)
        stats["filled"] += 1
        return "<li>" + new_li + "</li>"

    return LI_RE.sub(_sub_li, html), stats


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pages_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "pages")
    files = sorted(f for f in os.listdir(pages_dir) if re.fullmatch(r"daily-\d{4}-\d{2}-\d{2}\.html", f))
    if not files:
        print(f"[完成] {pages_dir} 下没有 daily-*.html")
        return

    cache = {}
    total = {"filled": 0, "skipped": 0, "missing": 0}
    for name in files:
        path = os.path.join(pages_dir, name)
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        ids = _ids_of_page(html)
        if not ids:
            print(f"{name}: 未识别到论文，跳过")
            continue
        # 整页都已带作者行 → 直接跳过，不浪费 API 请求（脚本幂等）
        if html.count('class="authors"') >= len(ids):
            print(f"{name}: 已含作者行（{len(ids)} 篇），跳过")
            continue
        # 先取出本页缺失的作者，再统一查询
        fetch_authors(ids, cache)
        new_html, stats = patch_html(html, cache)
        if new_html != html:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_html)
        for k in total:
            total[k] += stats[k]
        print(f"{name}: 补全 {stats['filled']} 篇，跳过 {stats['skipped']} 篇，查不到作者 {stats['missing']} 篇")

    print(f"[完成] 共补全 {total['filled']} 篇，跳过 {total['skipped']} 篇，无作者 {total['missing']} 篇")


if __name__ == "__main__":
    main()
