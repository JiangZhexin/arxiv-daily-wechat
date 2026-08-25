# -*- coding: utf-8 -*-
"""
page_builder.py
根据每日抓取 + DeepSeek 总结生成静态 HTML 页面，供 GitHub Pages 部署。
微信模板消息点击后会跳转到这个页面查看完整论文清单。

页面结构（按分区组织）：
  - 顶部标题 + 元信息（日期、总篇数）
  - 分区目录（跳转锚点）
  - 每个分区一个 <section>，列出该区论文：
      [编号-链接到 arXiv] 中文标题
      💡 一句话总结
      👉 arXiv URL（可点击）
"""
import os


# 与 main.py 保持一致
CATEGORY_NAMES = {
    "math.DG": "微分几何",
    "math.GN": "一般拓扑",
    "math.GT": "几何拓扑",
    "math.GR": "群论",
    "math.MG": "度量几何",
    "math.NT": "数论",
}


def _category_label(primary: str) -> str:
    return CATEGORY_NAMES.get(primary, primary)


def _assign_section(p, categories):
    """论文归属分区：主分类命中目标列表则用主分类，否则用第一个命中的目标标签。"""
    if p["primary"] in categories:
        return p["primary"]
    for c in p["categories"]:
        if c in categories:
            return c
    return p["primary"]


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
       max-width: 780px; margin: 24px auto; padding: 0 16px; color: #222; line-height: 1.7; background: #fafafa; }
h1 { font-size: 1.7em; color: #1a1a1a; border-bottom: 2px solid #444; padding-bottom: 8px; }
.meta { color: #777; font-size: 0.92em; margin-bottom: 20px; }
nav.toc { background: #eef3f8; padding: 12px 16px; border-radius: 8px; margin-bottom: 24px; line-height: 1.9; }
nav.toc a { margin-right: 14px; color: #06c; text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
section { background: #fff; padding: 18px 24px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
h2 { color: #1a1a1a; margin-top: 0; font-size: 1.25em; }
ol { padding-left: 22px; }
li { margin-bottom: 18px; }
.title { font-weight: 600; color: #1a1a1a; }
.title a { color: #c0392b; text-decoration: none; }
.title a:hover { text-decoration: underline; }
.summary { color: #444; font-size: 0.95em; margin: 4px 0; }
.en-title { color: #888; font-size: 0.88em; font-style: italic; margin: 2px 0; }
.link { font-size: 0.85em; color: #888; word-break: break-all; }
.link a { color: #06c; }
details { margin: 4px 0; }
details summary { cursor: pointer; color: #555; font-size: 0.92em; margin-top: 2px; }
details p { margin: 6px 0 8px; color: #444; font-size: 0.93em; }
.ai-line { color: #444; font-size: 0.95em; margin: 2px 0; }
.history { margin-bottom: 16px; font-size: 0.9em; color: #555; line-height: 1.9; }
.history a { color: #06c; margin-right: 10px; text-decoration: none; }
.history a:hover { text-decoration: underline; }
.index-list { list-style: none; padding: 0; }
.index-list li { margin-bottom: 8px; }
.index-list a { display: inline-block; padding: 10px 16px; background: #fff; border: 1px solid #e0e0e0;
                border-radius: 8px; color: #06c; text-decoration: none; font-size: 1.05em; width: 100%; box-sizing: border-box; }
.index-list a:hover { background: #eef3f8; border-color: #06c; }
footer { color: #aaa; font-size: 0.85em; text-align: center; margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; }
"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_daily_html(papers, summaries, categories, date_str, base_url="https://arxiv.org/abs/", history_links=None):
    """生成完整的每日论文 HTML 页面字符串。

    history_links: 可选，历史页面文件名列表，如 ["daily-2026-08-23.html", ...]，会在顶部显示历史入口。
    """
    sections = {c: [] for c in categories}
    for p in papers:
        sec = _assign_section(p, categories)
        sections.setdefault(sec, []).append(p)

    active_sections = [(sec, sec_papers) for sec, sec_papers in sections.items() if sec_papers]

    out = []
    out.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    out.append(f"<title>arXiv 每日论文速览 · {date_str}</title>")
    out.append(f"<style>{_CSS}</style></head><body>")
    out.append(f"<h1>📚 arXiv 每日论文速览 · {date_str}</h1>")
    out.append(f'<div class="meta">共 {len(papers)} 篇论文 · 覆盖 {len(active_sections)} 个分类 · 由 arXiv API + DeepSeek 自动整理</div>')

    # 历史入口
    if history_links:
        links = "".join(f'<a href="{h}">{h[6:16]}</a>' for h in history_links)
        out.append(f'<div class="history">🏠 <a href="index.html">返回总目录</a> · 📅 历史：{links}</div>')
    else:
        out.append(f'<div class="history">🏠 <a href="index.html">返回总目录</a></div>')

    # 目录
    if active_sections:
        toc = ['<nav class="toc">']
        for sec, sec_papers in active_sections:
            label = _category_label(sec)
            toc.append(f'<a href="#{sec}">{label}（{len(sec_papers)}）</a>')
        toc.append("</nav>")
        out.append("\n".join(toc))

    for sec, sec_papers in active_sections:
        label = _category_label(sec)
        out.append(f'<section id="{sec}">')
        out.append(f"<h2>📂 {label} · {len(sec_papers)} 篇</h2>")
        out.append("<ol>")
        for p in sec_papers:
            info = summaries.get(p["id"], {})
            title_zh = _escape(info.get("title_zh") or p["title"])
            one_line = _escape(info.get("summary") or "（未生成总结）")
            ai_summary = _escape(info.get("ai_summary") or "")
            abstract_zh = _escape(info.get("abstract_zh") or "")
            abstract_en = _escape(p["summary"])
            en_title = _escape(p["title"])
            arxiv_url = f"{base_url}{p['id']}"

            blocks = [f'<div class="title">[<a href="{arxiv_url}" target="_blank" rel="noopener">{p["id"]}</a>] {title_zh}</div>']
            blocks.append(f'<div class="en-title">{en_title}</div>')
            if ai_summary:
                ai_lines = "".join(f"<div class='ai-line'>• {line}</div>" for line in ai_summary.splitlines() if line.strip())
                blocks.append(f'<details class="ai"><summary>🤖 AI 总结</summary>{ai_lines}</details>')
            blocks.append(f'<div class="summary">💡 {one_line}</div>')
            if abstract_zh:
                blocks.append(f'<details class="abs-zh"><summary>📖 中文摘要</summary><p>{abstract_zh}</p></details>')
            if abstract_en:
                blocks.append(f'<details class="abs-en"><summary>🌐 English Abstract</summary><p>{abstract_en}</p></details>')
            blocks.append(f'<div class="link">👉 <a href="{arxiv_url}" target="_blank" rel="noopener">{arxiv_url}</a></div>')
            out.append("<li>" + "".join(blocks) + "</li>")
        out.append("</ol></section>")

    out.append('<footer>由 <a href="https://arxiv.org">arXiv</a> API + <a href="https://www.deepseek.com">DeepSeek</a> 自动生成 · 微信公众号测试号推送</footer>')
    out.append("</body></html>")
    return "\n".join(out)


def write_daily_page(papers, summaries, categories, date_str, output_dir="pages", base_url="https://arxiv.org/abs/"):
    """
    生成今日 HTML 页面（daily-YYYY-MM-DD.html）和总目录首页（index.html）。
    index.html 是所有日期论文速览的索引汇总页（点击日期进入当天详情）。
    返回: (daily_path, index_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    import re

    # 扫描历史页面（不含今天）
    history = sorted(
        f for f in os.listdir(output_dir)
        if re.fullmatch(r"daily-\d{4}-\d{2}-\d{2}\.html", f) and f != f"daily-{date_str}.html"
    )
    history.reverse()  # 新的在前

    html = build_daily_html(papers, summaries, categories, date_str, base_url=base_url, history_links=history)

    daily_path = os.path.join(output_dir, f"daily-{date_str}.html")
    with open(daily_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 生成总目录索引页（列出所有日期，附当天论文篇数）
    index_html = build_index_html(output_dir)
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    return daily_path, index_path


def build_index_html(output_dir="pages"):
    """生成总目录索引页：列出 output_dir 里所有 daily-YYYY-MM-DD.html（新的在前），附当天论文篇数。"""
    import re

    files = sorted(
        f for f in os.listdir(output_dir)
        if re.fullmatch(r"daily-\d{4}-\d{2}-\d{2}\.html", f)
    )
    files.reverse()  # 新的在前

    items = []
    for f in files:
        date = f[6:16]
        count = None
        try:
            with open(os.path.join(output_dir, f), encoding="utf-8") as fh:
                content = fh.read()
            m = re.search(r"共 (\d+) 篇论文", content)
            count = m.group(1) if m else None
        except OSError:
            count = None
        label = f"{date}（{count} 篇）" if count else date
        items.append(f'<li><a href="{f}">📅 {label}</a></li>')

    if not items:
        items.append("<li>暂无每日速览，等下次抓取后生成。</li>")

    out = []
    out.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    out.append("<title>arXiv 每日论文速览 · 总目录</title>")
    out.append(f"<style>{_CSS}</style></head><body>")
    out.append("<h1>📚 arXiv 每日论文速览 · 总目录</h1>")
    out.append('<div class="meta">按日期浏览每天的论文速览 · 自动生成，每日更新</div>')
    out.append("<ul class='index-list'>" + "".join(items) + "</ul>")
    out.append('<footer>由 <a href="https://arxiv.org">arXiv</a> API + <a href="https://www.deepseek.com">DeepSeek</a> 自动生成 · 微信公众号测试号推送</footer>')
    out.append("</body></html>")
    return "\n".join(out)