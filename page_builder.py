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
footer { color: #aaa; font-size: 0.85em; text-align: center; margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; }
"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_daily_html(papers, summaries, categories, date_str, base_url="https://arxiv.org/abs/"):
    """生成完整的每日论文 HTML 页面字符串。"""
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
            en_title = _escape(p["title"])
            arxiv_url = f"{base_url}{p['id']}"
            out.append(
                "<li>"
                f'<div class="title">[<a href="{arxiv_url}" target="_blank" rel="noopener">{p["id"]}</a>] {title_zh}</div>'
                f'<div class="en-title">{en_title}</div>'
                f'<div class="summary">💡 {one_line}</div>'
                f'<div class="link">👉 <a href="{arxiv_url}" target="_blank" rel="noopener">{arxiv_url}</a></div>'
                "</li>"
            )
        out.append("</ol></section>")

    out.append('<footer>由 <a href="https://arxiv.org">arXiv</a> API + <a href="https://www.deepseek.com">DeepSeek</a> 自动生成 · 微信公众号测试号推送</footer>')
    out.append("</body></html>")
    return "\n".join(out)


def write_daily_page(papers, summaries, categories, date_str, output_dir="pages", base_url="https://arxiv.org/abs/"):
    """生成 HTML 文件并写入 output_dir/daily-YYYY-MM-DD.html，返回生成的文件路径。"""
    html = build_daily_html(papers, summaries, categories, date_str, base_url=base_url)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"daily-{date_str}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path