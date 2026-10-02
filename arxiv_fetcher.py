# -*- coding: utf-8 -*-
"""
arxiv_fetcher.py
从 arXiv 抓取指定分类（math.DG / math.GN / math.GT 等）最新公告的新论文。

为什么用 RSS 而不是搜索 API？
- arXiv 的搜索 API（export.arxiv.org/api/query）对新公告论文的索引有延迟
  （新论文在网页立即可见，但 API 搜索要过数小时到 1 天才收录），
  导致早上定时抓取经常拿到 0 篇。
- RSS 源（arxiv.org/rss/{分类}）与网页公告列表实时同步，没有索引延迟。

本模块只依赖标准库 xml.etree 和 requests。
"""
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

ARXIV_RSS_URL = "https://arxiv.org/rss/{cat}"
ARXIV_API_URL = "https://export.arxiv.org/api/query"

# arXiv Atom/RSS 用到的 XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# RSS 通道 pubDate 格式，如 "Wed, 26 Aug 2026 00:00:00 -0400"
_RSS_DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
]


def _parse_rss_date(raw: str):
    """解析 RSS 时间字符串，转成 UTC datetime。"""
    for fmt in _RSS_DATE_FORMATS:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# LaTeX 重音命令 → Unicode 组合符号（用 NFC 合成成带音标的字母）
_ACCENT_COMBINING = {
    "'": "\u0301",   # 尖音符 \'e → é
    "`": "\u0300",   # 抑音符 \`e → è
    "^": "\u0302",   # 扬抑符 \^o → ô
    "~": "\u0303",   # 波浪号 \~n → ñ
    "=": "\u0304",   # 长音符 \=o → ō
    "u": "\u0306",   # 短音符 \u{a} → ă
    ".": "\u0307",   # 上点 \.z → ż
    '"': "\u0308",   # 分音符 \"o → ö
    "r": "\u030a",   # 上圈 \r{a} → å
    "H": "\u030b",   # 双尖音 \H{o} → ő
    "v": "\u030c",   # 抑扬符 \v{s} → š
    "c": "\u0327",   # 下加符 \c{c} → ç
    "k": "\u0328",   # 反尾形符 \k{a} → ą
    "d": "\u0323",   # 下点 \d{u} → ụ
    "b": "\u0331",   # 下横线 \b{h} → ẖ
}

# \o \ss \ae 之类的符号命令 → 字符
_SYMBOL_COMMANDS = {
    "ss": "ß", "o": "ø", "O": "Ø", "l": "ł", "L": "Ł",
    "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
}

_LETTER = r"[A-Za-z\u00c0-\u024f]"


def _clean_author_name(name: str) -> str:
    """把 arXiv 里的 LaTeX 转义作者名还原成普通文本。

    例：``Manuel Cruz-L\\'opez`` → ``Manuel Cruz-López``；
        ``{\\O}ystein Skarts{\\ae}terhagen`` → ``Øystein Skartsæterhagen``。
    """
    s = (name or "").strip()
    if not s:
        return ""

    # 1) 只起包裹作用的命令，保留其中内容
    s = re.sub(
        r"\\(?:text|textrm|textit|textnormal|texttt|textsc|textup|mathrm|mathbf|mathit|mathsf|mathtt|mbox|hbox|emph|mathrm)"
        r"\s*\{([^{}]*)\}",
        r"\1",
        s,
    )
    # {\bf A} / \it A 之类的字体切换命令，直接删掉
    s = re.sub(r"\\(?:bf|it|rm|sl|sc|tt|tiny|small|large|normalsize)(?=[A-Za-z{\s])", "", s)
    # \i \j（无点字母，常用于 \'\i）
    s = re.sub(r"\\i(?![A-Za-z])", "\u0131", s)
    s = re.sub(r"\\j(?![A-Za-z])", "\u0237", s)

    # 2) 重音命令：\'e、\'{e}、\' e 都归一为带音标字母
    def _accent(m):
        cmd, letter = m.group(1), m.group(2)
        comb = _ACCENT_COMBINING.get(cmd)
        if not comb:
            return letter
        # ı + 尖音符没有预组合字符，用 i 合成（如 \'\i → í）
        if letter == "\u0131":
            letter = "i"
        elif letter == "\u0237":
            letter = "j"
        return unicodedata.normalize("NFC", letter + comb)

    s = re.sub(r"\\([`'\"^~=.uvHckrdb])\s*\{?(" + _LETTER + r")\}?", _accent, s)

    # 3) 符号命令（\ss \o \ae …），长命令优先，且后面不能紧跟字母。
    #    LaTeX 里控制词后的空格会被吞掉（S\o rensen → Sørensen），这里一并处理。
    s = re.sub(
        r"\\(ss|aa|AA|ae|AE|oe|OE|o|O|l|L)(?![A-Za-z]) ?",
        lambda m: _SYMBOL_COMMANDS.get(m.group(1), m.group(1)),
        s,
    )

    # 4) 兜底：清掉残留的花括号与反斜杠命令，压缩空白
    s = re.sub(r"\\(?:[A-Za-z]+|.)", "", s)
    s = s.replace("{", "").replace("}", "")
    s = " ".join(s.split())
    # 去掉清洗后可能留下的首尾孤立标点
    s = s.strip(" ,;")
    return s


def _parse_authors(item) -> list:
    """从 RSS item 解析作者列表（arXiv 的 dc:creator 是逗号分隔的作者串）。"""
    chunks = [el.text for el in item.findall("dc:creator", NS) if el.text]
    if not chunks:
        fallback = item.findtext("dc:creator", default="", namespaces=NS) or ""
        chunks = [fallback]

    authors = []
    for chunk in chunks:
        for name in str(chunk).split(","):
            cleaned = _clean_author_name(name)
            if cleaned and cleaned not in authors:
                authors.append(cleaned)
    return authors


def _fetch_missing_authors(papers, headers, timeout=60):
    """RSS 没给作者时，用 arXiv API 按 id 批量补齐（每批最多 100 个 id）。"""
    missing = [p["id"] for p in papers if not p.get("authors")]
    if not missing:
        return
    by_id = {p["id"]: p for p in papers}
    for i in range(0, len(missing), 100):
        batch = missing[i : i + 100]
        try:
            resp = requests.get(
                ARXIV_API_URL,
                params={"id_list": ",".join(batch), "max_results": len(batch)},
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except (requests.RequestException, ET.ParseError) as exc:
            print(f"  [警告] 补齐作者失败（{len(batch)} 篇）: {exc}")
            continue
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            link = entry.findtext("{http://www.w3.org/2005/Atom}id", default="") or ""
            pid = link.split("/abs/")[-1].strip()
            names = [
                _clean_author_name(a.findtext("{http://www.w3.org/2005/Atom}name", default="") or "")
                for a in entry.findall("{http://www.w3.org/2005/Atom}author")
            ]
            if pid in by_id:
                by_id[pid]["authors"] = [n for n in names if n]
        print(f"  [调试] 已用 arXiv API 补齐 {len(batch)} 篇的作者")


def _fetch_rss(cat, headers, timeout=60):
    """抓取单个分类的 RSS，返回 (根元素, 文本)。"""
    url = ARXIV_RSS_URL.format(cat=cat)
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return ET.fromstring(resp.text), resp.text


def fetch_new_papers(
    categories,
    hours_back: int = 30,
    max_results: int = 300,
    retries: int = 3,
):
    """
    抓取最近一次公告（RSS）中的新论文，按分类合并、去重。

    参数:
        categories: 分类列表，如 ["math.DG", "math.GN", "math.GT"]
        hours_back: 只接收"新鲜"的 RSS（RSS 生成时间距今在 hours_back*2 小时内）。
                    默认 30：周末 RSS 停留在周五，周一早上跑时约 72h，
                    主流程检测到 0 篇会自动用 72 小时窗口重查，兼容周末。
        max_results: 保留兼容参数（RSS 方案下不使用）
        retries: 请求失败时的重试次数

    返回:
        论文列表，每项为 dict:
            id, url, title, summary, published(datetime), primary, categories, authors
        按发布时间从新到旧排序，已按 id 去重。
    """
    headers = {"User-Agent": "arxiv-daily-wechat/1.0 (arXiv daily digest; contact: github.com/JiangZhexin/arxiv-daily-wechat)"}
    now = datetime.now(timezone.utc)

    papers = []
    seen_ids = set()

    for cat in categories:
        root = None
        resp_text = ""
        for attempt in range(retries):
            try:
                root, resp_text = _fetch_rss(cat, headers)
                break
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise RuntimeError(f"arXiv RSS 请求失败（{cat}）: {exc}") from exc
                time.sleep(5 * (attempt + 1))

        # 诊断日志
        print(f"  [调试] RSS {cat}: 响应 {len(resp_text)} 字符")

        # RSS 新鲜度：channel pubDate（美东日期），太久没更新则跳过该分类
        feed_dt = None
        pub_raw = root.findtext("channel/pubDate", default="") or root.findtext("./pubDate", default="")
        if pub_raw:
            feed_dt = _parse_rss_date(pub_raw)
        if feed_dt is not None and (now - feed_dt) > timedelta(hours=hours_back * 2):
            print(f"  [跳过] RSS {cat} 生成于 {feed_dt:%Y-%m-%d %H:%M} UTC（超过 {hours_back*2}h 未更新，可能无新公告）")
            continue

        # 解析条目
        for item in root.iter("item"):
            link = item.findtext("link", default="") or ""
            short_id = link.split("/abs/")[-1].strip()
            if not short_id or short_id in seen_ids:
                continue

            # announce_type: new / cross / replace（replace 是更新，不算新论文）
            announce = item.findtext("arxiv:announce_type", default="", namespaces=NS) or ""
            if announce == "replace":
                continue

            title = " ".join((item.findtext("title", default="") or "").split())
            desc = item.findtext("description", default="") or ""
            # 摘要 = "Abstract: " 之后的内容
            abstract = desc.split("Abstract: ", 1)[-1] if "Abstract: " in desc else desc
            abstract = " ".join(abstract.split())

            authors = _parse_authors(item)

            all_categories = [c.text.strip() for c in item.findall("category") if c.text and c.text.strip()]
            primary = all_categories[0] if all_categories else cat

            published = feed_dt or now

            seen_ids.add(short_id)
            papers.append(
                {
                    "id": short_id,
                    "url": f"https://arxiv.org/abs/{short_id}",
                    "title": title,
                    "summary": abstract,
                    "published": published,
                    "primary": primary,
                    "categories": all_categories,
                    "authors": authors,
                }
            )

    papers.sort(key=lambda p: p["published"], reverse=True)
    print(f"  [调试] 合并后共 {len(papers)} 篇（去重后）")

    # RSS 偶尔不给 dc:creator，用 API 兜底补齐作者
    _fetch_missing_authors(papers, headers)

    return papers
