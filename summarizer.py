# -*- coding: utf-8 -*-
"""
summarizer.py
调用 DeepSeek（OpenAI 兼容接口）为论文批量生成「中文标题 + 一句话总结」。

- 接口: POST {base_url}/chat/completions
- 模型: deepseek-chat（价格便宜，足够做短摘要）
- 每批最多 batch_size 篇，避免超出上下文
- 输出强制 JSON，失败自动重试一次
"""
import json
import time

import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = (
    "你是一名精通微分几何、一般拓扑学与几何拓扑学的科研助理。"
    "用户会给你一批 arXiv 论文的编号、英文标题和英文摘要。"
    "请为每篇论文输出：1) 中文翻译标题 title_zh；"
    "2) 一句话中文总结 summary，不超过 60 字，说明论文解决什么问题、核心贡献是什么；"
    "3) 摘要的中文翻译 abstract_zh，忠实翻译英文摘要，尽量完整但不超过 250 字，保留数学专业术语；"
    "4) 3-5 句 AI 总结 ai_summary，用中文，逐句概括研究问题、方法、主要结果与意义，共 60-150 字，用换行分隔每句。"
    "不要输出任何多余文字，严格返回 JSON："
    '{"papers": [{"id": "论文编号", "title_zh": "中文标题", "summary": "一句话总结", "abstract_zh": "中文摘要翻译", "ai_summary": "3-5句AI总结"}]}'
)

USER_TEMPLATE = (
    "以下是本批 {count} 篇 arXiv 论文（编号 + 英文标题 + 摘要）：\n\n"
    "{body}"
)


def _call_chat(api_key, base_url, model, user_content, timeout=120):
    """调用一次 chat/completions，返回解析后的 JSON 对象。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},  # DeepSeek 支持强制 JSON 输出
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    return json.loads(content)


def summarize_papers(papers, api_key, base_url=None, model="deepseek-chat", batch_size=20):
    """
    对论文列表批量生成中文总结。

    参数:
        papers: arxiv_fetcher.fetch_new_papers 的返回结果
        api_key: DeepSeek API Key
        base_url: 接口地址，默认 https://api.deepseek.com
        model: 模型名，默认 deepseek-chat
        batch_size: 每批论文数，默认 20

    返回:
        dict: {论文id: {"title_zh": ..., "summary": ..., "abstract_zh": ...}}
        失败的单篇不会被加入结果（不影响其他篇）。
    """
    base_url = base_url or DEFAULT_BASE_URL
    results = {}

    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        lines = []
        for p in batch:
            # 摘要截断到 2000 字符，控制 token 成本
            abstract = p["summary"][:2000]
            lines.append(f"[{p['id']}] {p['title']}\nAbstract: {abstract}")
        user_content = USER_TEMPLATE.format(count=len(batch), body="\n\n".join(lines))

        parsed = None
        for attempt in range(2):  # 失败重试一次
            try:
                parsed = _call_chat(api_key, base_url, model, user_content)
                break
            except (requests.RequestException, ValueError, KeyError) as exc:
                if attempt == 1:
                    print(f"  [警告] 第 {i // batch_size + 1} 批总结失败: {exc}")
                    parsed = None
                else:
                    time.sleep(3)

        if not parsed or "papers" not in parsed:
            continue

        for item in parsed["papers"]:
            pid = str(item.get("id", "")).strip()
            if pid and isinstance(item.get("title_zh"), str):
                results[pid] = {
                    "title_zh": item["title_zh"],
                    "summary": str(item.get("summary", "")),
                    "abstract_zh": str(item.get("abstract_zh", "")),
                    "ai_summary": str(item.get("ai_summary", "")),
                }

    return results


if __name__ == "__main__":
    # 本地自测（需要环境变量 DEEPSEEK_API_KEY）：
    # python summarizer.py
    import os
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("请先设置环境变量 DEEPSEEK_API_KEY 再自测。")
        sys.exit(1)

    from arxiv_fetcher import fetch_new_papers

    demo = fetch_new_papers(["math.DG"], hours_back=24, max_results=5)
    print(f"测试论文数: {len(demo)}")
    out = summarize_papers(demo, api_key=key)
    for pid, info in out.items():
        print(f"[{pid}] {info['title_zh']} — {info['summary']}")
