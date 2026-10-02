# -*- coding: utf-8 -*-
"""
summarizer.py
调用 DeepSeek（OpenAI 兼容接口）为论文批量生成「中文标题 + 一句话总结」。

- 接口: POST {base_url}/chat/completions
- 模型: deepseek-chat（价格便宜，足够做短摘要）
- 每批最多 batch_size 篇，避免超出上下文
- 输出强制 JSON，失败自动重试一次；仍失败则把这一批拆半再试，
  避免「一篇的坏数据拖垮整批 20 篇」
"""
import json
import re
import time

import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"

# 模型偶尔会在中文里带出 LaTeX 反斜杠命令（\frac、\nabla、\times …）。在 JSON 里它们有两种坏法：
#   1) 非法转义（\L \c \p …）→ json.loads 直接抛错，整批 20 篇一起作废；
#   2) 「合法但变义」：\f \b \n \t \r 本身是合法 JSON 转义（换页/退格/换行/制表/回车），
#      于是 \frac 变成「换页符+rac」、\nabla 变成「换行+abla」——不报错，但文本被悄悄弄坏。
# 下面的扫描器只处理「JSON 字符串内部」的反斜杠，把会被误读的那些双写回字面量。
_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_UNICODE_ESCAPE = re.compile(r"u[0-9a-fA-F]{4}")


def _repair_latex_escapes(text):
    """把 JSON 字符串内部会被误读的反斜杠双写为字面量。

    逐字符扫描而不是正则替换，因为必须区分「单个反斜杠」和「已经转义过的 \\\\」，
    否则 \\\\frac 会被再次转义成 \\\\\\frac，反而把内容改坏。
    """
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = False
            out.append(ch)
            i += 1
            continue
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        # 已经是「正确转义、且不可能来自 LaTeX」的形式：原样保留
        if nxt in ('"', "\\", "/"):
            out.append(text[i : i + 2])
            i += 2
            continue
        # \uXXXX（4 位十六进制）保留；\underline 这种由下面按 LaTeX 处理
        if nxt == "u" and _UNICODE_ESCAPE.match(text[i + 1 : i + 5]):
            out.append(text[i : i + 6])
            i += 6
            continue
        # \n \t \r：后面紧跟拉丁字母更像 LaTeX（\nabla \times \rho），
        # 后面是中文/标点/行尾才是真的换行制表回车
        if nxt in ("n", "t", "r"):
            after = text[i + 2] if i + 2 < n else ""
            if not (after.isascii() and after.isalpha()):
                out.append(text[i : i + 2])
                i += 2
                continue
        # 其余一律当 LaTeX 字面量：反斜杠双写
        out.append("\\\\")
        i += 1
    return "".join(out)

SYSTEM_PROMPT = (
    "你是一名精通微分几何、一般拓扑学与几何拓扑学的科研助理。"
    "用户会给你一批 arXiv 论文的编号、英文标题和英文摘要。"
    "请为每篇论文输出：1) 中文翻译标题 title_zh；"
    "2) 一句话中文总结 summary，不超过 60 字，说明论文解决什么问题、核心贡献是什么；"
    "3) 摘要的中文翻译 abstract_zh，忠实翻译英文摘要，尽量完整但不超过 250 字，保留数学专业术语；"
    "4) 3-5 句 AI 总结 ai_summary，用中文，逐句概括研究问题、方法、主要结果与意义，共 60-150 字，用换行分隔每句。"
    "【格式硬性要求】所有文本用纯中文/英文书写，**不要输出任何 LaTeX 命令或反斜杠**"
    "（例如写成「流形 M 上的度量 g」、「拉普拉斯算子」、「L2 空间」、「星号卷积」这种纯文本形式，"
    "必要符号用 Unicode，如 Λ、∇、⊗、≤、α、β）；"
    "字符串内部出现双引号请改用中文引号「」，不要输出任何多余文字，严格返回 JSON："
    '{"papers": [{"id": "论文编号", "title_zh": "中文标题", "summary": "一句话总结", "abstract_zh": "中文摘要翻译", "ai_summary": "3-5句AI总结"}]}'
)

USER_TEMPLATE = (
    "以下是本批 {count} 篇 arXiv 论文（编号 + 英文标题 + 摘要）：\n\n"
    "{body}"
)


def _loads_lenient(text):
    """把模型返回的内容尽量解析成 JSON（对非法转义做兜底修复）。

    解析顺序：原样 → 修复非法反斜杠转义 → 再清掉字符串里的裸换行。
    都失败才抛错，交给上层重试/拆批。
    """
    if not text or not text.strip():
        raise ValueError("模型返回为空")
    s = _CODE_FENCE.sub("", text.strip())
    repaired = _repair_latex_escapes(s)
    last_exc = None
    # 优先用修复版：它只在「反斜杠会被 JSON 误读」时才改变文本，正常内容下与原样等价
    for candidate in (repaired, s, " ".join(repaired.splitlines())):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc
    raise ValueError(f"JSON 解析失败: {last_exc}")


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
    return _loads_lenient(content)


def _summarize_batch(papers, api_key, base_url, model, results, depth=0):
    """总结一批论文；失败时把这一批拆成两半再试（递归到单篇为止）。"""
    if not papers:
        return
    lines = []
    for p in papers:
        # 摘要截断到 2000 字符，控制 token 成本
        abstract = p["summary"][:2000]
        lines.append(f"[{p['id']}] {p['title']}\nAbstract: {abstract}")
    user_content = USER_TEMPLATE.format(count=len(papers), body="\n\n".join(lines))

    parsed = None
    last_exc = None
    for attempt in range(2):  # 失败重试一次
        try:
            parsed = _call_chat(api_key, base_url, model, user_content)
            break
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(3)

    if isinstance(parsed, dict) and isinstance(parsed.get("papers"), list):
        got = 0
        for item in parsed["papers"]:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id", "")).strip()
            if pid and isinstance(item.get("title_zh"), str):
                results[pid] = {
                    "title_zh": item["title_zh"],
                    "summary": str(item.get("summary", "")),
                    "abstract_zh": str(item.get("abstract_zh", "")),
                    "ai_summary": str(item.get("ai_summary", "")),
                }
                got += 1
        if got:
            return

    # 整批失败：拆半重试，避免个别论文的脏数据拖垮整批
    if len(papers) > 1:
        mid = len(papers) // 2
        print(f"  [警告] {len(papers)} 篇一批总结失败（{last_exc}），拆成 {mid}+{len(papers) - mid} 篇重试")
        _summarize_batch(papers[:mid], api_key, base_url, model, results, depth + 1)
        _summarize_batch(papers[mid:], api_key, base_url, model, results, depth + 1)
    else:
        print(f"  [警告] 论文 {papers[0].get('id')} 总结失败（已跳过该篇）: {last_exc}")


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
    total_batches = (len(papers) + batch_size - 1) // batch_size

    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        print(f"      第 {i // batch_size + 1}/{total_batches} 批（{len(batch)} 篇）...")
        _summarize_batch(batch, api_key, base_url, model, results)

    missing = [p["id"] for p in papers if p["id"] not in results]
    if missing:
        print(f"      [提示] {len(missing)} 篇未拿到 AI 总结（网页上这几篇只显示英文摘要）: {', '.join(missing[:8])}"
              + (" ..." if len(missing) > 8 else ""))
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
