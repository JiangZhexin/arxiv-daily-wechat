# -*- coding: utf-8 -*-
"""
main.py —— arXiv 每日论文速览（抓取 + DeepSeek 中文总结 + 微信公众号推送）

用法:
    本地预览（不发微信）:  python main.py --dry-run
    本地正式运行:           python main.py
    查看帮助:               python main.py --help

配置优先级: 环境变量 > config.json（config.json 由 config.example.json 复制改名而来）
环境变量清单（GitHub Actions 里通过 Secrets/Variables 注入）:
    ARXIV_CATEGORIES      逗号分隔的分类，如 "math.DG,math.GN,math.GT"
    ARXIV_HOURS_BACK      回看小时数，默认 36
    DEEPSEEK_API_KEY      DeepSeek 密钥（必填）
    DEEPSEEK_BASE_URL     默认 https://api.deepseek.com
    DEEPSEEK_MODEL        默认 deepseek-chat
    WECHAT_APP_ID         微信公众号测试号 appID（必填）
    WECHAT_APP_SECRET     测试号 appsecret（必填）
    WECHAT_TEMPLATE_ID    测试号模板消息模板 ID（必填）
    WECHAT_OPENID         测试号测试者（你自己）的 openid（必填）
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from arxiv_fetcher import fetch_new_papers
from summarizer import summarize_papers
from wechat_push import WeChatPusher

# 微信模板字段 → 推送内容 的默认映射
# 模板字段名以你在测试号后台选的模板为准，可在 config.json 的 template_fields 里改
DEFAULT_TEMPLATE_FIELDS = {
    "first": "first",
    "keyword1": "keyword1",
    "keyword2": "keyword2",
    "keyword3": "keyword3",
    "remark": "remark",
}

# 消息模式：
#   digest   = 速览模式（默认）：每条消息含多篇论文（编号+中文标题+一句话总结），一天 30 篇也只要 5 条消息
#   detailed = 详细模式：每篇 1 条消息，含一句话总结 + 中英文摘要，可点击跳转原文
DEFAULT_MESSAGE_MODE = "digest"

# 详细模式：每条消息 1 篇（中英文摘要完整展示）
DETAILED_PAPERS_PER_MESSAGE = 1

# 分类中文名，用于消息里展示
CATEGORY_NAMES = {
    "math.DG": "微分几何",
    "math.GN": "一般拓扑",
    "math.GT": "几何拓扑",
    "math.GR": "群论",
    "math.MG": "度量几何",
    "math.NT": "数论",
}

# 默认抓取的 arXiv 分类（按需增删）
DEFAULT_CATEGORIES = ["math.DG", "math.GN", "math.GT", "math.GR", "math.MG", "math.NT"]

# 已推送论文记录（防止窗口扩大后重复推送；由 workflow 提交回仓库保留）
STATE_FILE = "last_pushed.json"


def _load_pushed_ids():
    """读取已推送的论文 id 集合。文件不存在或损坏时返回空集合。"""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(str(x) for x in data.get("ids", []))
    except (OSError, ValueError):
        return set()


def _save_pushed_ids(ids):
    """把已推送论文 id 集合写入状态文件。"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(ids)}, f, ensure_ascii=False)


def _utf8():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")


def load_config():
    """读取配置：环境变量优先，其次 config.json。"""
    cfg = {}

    # 1) config.json（本地使用，密钥不入库）
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)

    # 2) 环境变量覆盖
    categories_env = os.environ.get("ARXIV_CATEGORIES")
    arxiv_cfg = cfg.get("arxiv", {})
    categories = (
        [c.strip() for c in categories_env.split(",") if c.strip()]
        if categories_env
        else arxiv_cfg.get("categories", DEFAULT_CATEGORIES)
    )
    hours_back = int(os.environ.get("ARXIV_HOURS_BACK") or arxiv_cfg.get("hours_back", 30))
    max_papers_per_run = int(os.environ.get("ARXIV_MAX_PAPERS") or arxiv_cfg.get("max_papers_per_run", 200))

    ds_cfg = cfg.get("deepseek", {})
    deepseek = {
        "api_key": os.environ.get("DEEPSEEK_API_KEY") or ds_cfg.get("api_key", ""),
        "base_url": os.environ.get("DEEPSEEK_BASE_URL") or ds_cfg.get("base_url", "https://api.deepseek.com"),
        "model": os.environ.get("DEEPSEEK_MODEL") or ds_cfg.get("model", "deepseek-chat"),
    }

    wx_cfg = cfg.get("wechat", {})
    fields = dict(DEFAULT_TEMPLATE_FIELDS)
    fields.update(wx_cfg.get("template_fields", {}))
    mode = (os.environ.get("WECHAT_MODE") or wx_cfg.get("mode") or DEFAULT_MESSAGE_MODE).strip().lower()
    if mode not in ("digest", "detailed"):
        mode = DEFAULT_MESSAGE_MODE
    wechat = {
        "app_id": os.environ.get("WECHAT_APP_ID") or wx_cfg.get("app_id", ""),
        "app_secret": os.environ.get("WECHAT_APP_SECRET") or wx_cfg.get("app_secret", ""),
        "template_id": os.environ.get("WECHAT_TEMPLATE_ID") or wx_cfg.get("template_id", ""),
        "user_openid": os.environ.get("WECHAT_OPENID") or wx_cfg.get("user_openid", ""),
        "template_fields": fields,
        "mode": mode,
    }

    return {
        "arxiv": {
            "categories": categories,
            "hours_back": hours_back,
            "max_papers_per_run": max_papers_per_run,
        },
        "deepseek": deepseek,
        "wechat": wechat,
    }


def _category_label(primary: str) -> str:
    return CATEGORY_NAMES.get(primary, primary)


def _assign_section(p, categories):
    """
    确定一篇论文归属哪个目标分区：
    主分类是目标分区 → 用主分类；否则用第一个命中的目标分类标签。
    """
    if p["primary"] in categories:
        return p["primary"]
    for c in p["categories"]:
        if c in categories:
            return c
    return p["primary"]


def build_messages(papers, summaries, template_fields, categories, date_str, mode=DEFAULT_MESSAGE_MODE, page_url=None):
    """
    把论文列表 + 总结整理成模板消息。

    mode="digest"   ：速览模式（默认），按分区归组去重，每个分区一条消息（编号+中文标题+一句话总结）
    mode="detailed" ：详细模式，每篇 1 条消息，含一句话总结 + 中英文摘要，可点击跳转原文

    page_url: 速览消息点击跳转的网页 URL（如 GitHub Pages 的每日推文页面）。
              若提供，速览消息点开会跳转到该网页（推荐，详情看网页）；不传则不跳转。

    返回: list[dict]，每个 dict:
        {"data": {模板字段: {...}}, "url": "点击消息跳转的链接（可选）"}
    """
    category_text = "、".join(_category_label(c) for c in categories)
    keyword3_text = date_str

    f, k1, k2, k3, r = (
        template_fields["first"],
        template_fields["keyword1"],
        template_fields["keyword2"],
        template_fields["keyword3"],
        template_fields["remark"],
    )

    def _base_data(remark_text, first_text, keyword1_text, keyword2_text):
        return {
            f: {"value": first_text},
            k1: {"value": keyword1_text},
            k2: {"value": keyword2_text},
            k3: {"value": keyword3_text},
            r: {"value": remark_text},
        }

    def _cut(text, limit):
        return text[:limit] + ("…" if len(text) > limit else "")

    messages = []

    if mode == "detailed":
        # ---------- 详细模式：每篇 1 条，含中英文摘要 ----------
        first_text = "📚 arXiv 每日论文速览"
        keyword1_text = category_text
        keyword2_text = f"今日新增 {len(papers)} 篇"
        for p in papers:
            info = summaries.get(p["id"], {})
            title_zh = info.get("title_zh") or p["title"]
            one_line = info.get("summary") or "（未生成总结）"
            abstract_en = _cut(p["summary"], 220)
            abstract_zh = info.get("abstract_zh") or "（未生成翻译）"
            label = _category_label(p["primary"])

            remark_text = (
                f"[{p['id']}] {title_zh}（{label}）\n"
                f"💡 {one_line}\n\n"
                f"【EN Abstract】\n{abstract_en}\n\n"
                f"【中文摘要】\n{abstract_zh}"
            )
            if len(remark_text) > 600:
                remark_text = _cut(remark_text, 590)
            messages.append({"data": _base_data(remark_text, first_text, keyword1_text, keyword2_text), "url": p["url"]})
        return messages

    # ---------- 速览模式（默认）：只发 1 条汇总消息，包含各分区统计，点击跳转网页看详情 ----------
    # 先按分区归类（跨分区重复的论文只归到一个分区）
    sections = {c: [] for c in categories}
    for p in papers:
        sec = _assign_section(p, categories)
        sections.setdefault(sec, []).append(p)

    # 汇总消息：各分区篇数统计
    lines = []
    for sec in categories:
        count = len(sections.get(sec, []))
        if count:
            lines.append(f"{_category_label(sec)}：{count} 篇")
    lines.append("")
    lines.append("📌 点击消息查看全部论文的 AI 总结、中英文摘要与 arXiv 链接")

    remark_text = "\n".join(lines)
    if len(remark_text) > 600:
        remark_text = _cut(remark_text, 590)

    first_text = "📚 arXiv 每日论文速览"
    keyword1_text = f"共 {len(papers)} 篇"
    keyword2_text = date_str
    keyword3_text = "、".join(_category_label(c) for c in categories)

    messages.append(
        {
            "data": _base_data(remark_text, first_text, keyword1_text, keyword2_text),
            "url": page_url,
        }
    )

    return messages


def main():
    _utf8()
    parser = argparse.ArgumentParser(description="arXiv 每日论文速览：抓取 + DeepSeek 总结 + 微信推送")
    parser.add_argument("--dry-run", action="store_true", help="只抓取和总结并打印结果，不发送微信")
    parser.add_argument("--max-papers", type=int, default=0, help="最多处理多少篇论文（0 表示不限制，用于测试）")
    args = parser.parse_args()

    cfg = load_config()
    arxiv_cfg, ds_cfg, wx_cfg = cfg["arxiv"], cfg["deepseek"], cfg["wechat"]

    if not ds_cfg["api_key"]:
        print("[错误] 缺少 DeepSeek API Key（设置 DEEPSEEK_API_KEY 或在 config.json 填写）")
        sys.exit(1)
    if not args.dry_run and not (wx_cfg["app_id"] and wx_cfg["app_secret"] and wx_cfg["template_id"] and wx_cfg["user_openid"]):
        print("[错误] 非 dry-run 模式需要完整微信配置（WECHAT_APP_ID / WECHAT_APP_SECRET / WECHAT_TEMPLATE_ID / WECHAT_OPENID）")
        sys.exit(1)

    # 1) 抓取
    print(f"[1/3] 正在从 arXiv 抓取 {', '.join(arxiv_cfg['categories'])} 最近 {arxiv_cfg['hours_back']} 小时的新论文 ...")
    papers = fetch_new_papers(arxiv_cfg["categories"], hours_back=arxiv_cfg["hours_back"])
    if args.max_papers > 0:
        papers = papers[: args.max_papers]

    # 兼容 arXiv API 对当天新论文的索引延迟：小窗口 0 篇时，自动扩大到 72 小时重查
    if not papers:
        print("      [提示] 当前窗口无结果（arXiv 索引可能有延迟），扩大到 72 小时重查 ...")
        papers = fetch_new_papers(arxiv_cfg["categories"], hours_back=72)
        if args.max_papers > 0:
            papers = papers[: args.max_papers]
    print(f"      共抓到 {len(papers)} 篇")

    if not papers:
        print("[完成] 今天没有新论文，不推送。")
        return

    # 2) 去重：过滤掉已推送过的论文（记录在 last_pushed.json，随仓库提交保留）
    pushed_ids = _load_pushed_ids()
    new_papers = [p for p in papers if p["id"] not in pushed_ids]
    if not new_papers:
        print(f"[完成] 没有新论文（窗口内 {len(papers)} 篇均已推送过），不重复推送。")
        return
    if len(new_papers) < len(papers):
        print(f"      [去重] 已推送过 {len(papers) - len(new_papers)} 篇，本次实际新增 {len(new_papers)} 篇")
    papers = new_papers

    # 3) 总结（全量论文都总结，网页需要全部）
    print(f"[2/3] 调用 DeepSeek（{ds_cfg['model']}）生成中文总结 ...")
    summaries = summarize_papers(papers, api_key=ds_cfg["api_key"], base_url=ds_cfg["base_url"], model=ds_cfg["model"])
    print(f"      成功总结 {len(summaries)}/{len(papers)} 篇")

    # 3) 组织消息（先算好 page_url 再传给 build_messages）
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mode = wx_cfg.get("mode", DEFAULT_MESSAGE_MODE)

    # 单次最多推送篇数：仅详细模式（每篇 1 条消息）时限制论文数，防止微信刷屏；
    # 速览汇总模式（digest）微信只发 1 条统计消息，不截断，网页显示全部论文
    all_papers = papers
    if mode == "detailed" and len(papers) > arxiv_cfg["max_papers_per_run"]:
        print(f"      [提示] 论文较多，详细模式本次仅推送最新的 {arxiv_cfg['max_papers_per_run']} 篇（可调大 max_papers_per_run）")
        papers = papers[: arxiv_cfg["max_papers_per_run"]]

    # 若配置了 PAGE_BASE_URL（GitHub Pages 推文页地址），先生成页面文件并拼出 url
    # 页面用全部论文（all_papers），微信详细模式才截断
    page_base_url = os.environ.get("PAGE_BASE_URL", "").strip()
    page_url = None
    if page_base_url and not args.dry_run:
        try:
            from page_builder import write_daily_page
            daily_path, index_path = write_daily_page(all_papers, summaries, arxiv_cfg["categories"], date_str, output_dir="pages")
            page_url = page_base_url.rstrip("/") + "/" + os.path.basename(daily_path)
            print(f"      已生成推文页面: {daily_path} + {index_path}")
        except Exception as exc:
            print(f"  [警告] 生成推文页面失败（不影响微信推送）: {exc}")
            page_url = None

    messages = build_messages(papers, summaries, wx_cfg["template_fields"], arxiv_cfg["categories"], date_str, mode=mode, page_url=page_url)
    if mode == "digest":
        jump_hint = f" → 点击跳转推文页: {page_url}" if page_url else ""
        print(f"[3/3] 模式=速览汇总，共 {len(messages)} 条微信消息（1 条汇总，含各分区统计）{jump_hint}")
    else:
        print(f"[3/3] 模式=详细，共组织 {len(messages)} 条微信模板消息（每篇 1 条）")

    if args.dry_run:
        print("\n================  dry-run 预览 ================")
        for idx, msg in enumerate(messages, 1):
            jump = f" |  点击跳转: {msg['url']}" if msg.get("url") else ""
            print(f"\n----- 消息 {idx}{jump} -----")
            for k, v in msg["data"].items():
                print(f"{k}: {v['value']}")
        print("\n[dry-run] 仅预览，未发送微信。")
        return

    # 4) 推送
    pusher = WeChatPusher(wx_cfg["app_id"], wx_cfg["app_secret"], wx_cfg["template_id"], wx_cfg["user_openid"])
    sent = pusher.send_batch(messages)
    print(f"[完成] 已发送 {sent} 条消息到微信，公众号: 测试号")

    # 5) 记录本次已推送的论文 id（去重）
    _save_pushed_ids(pushed_ids | {p["id"] for p in papers})
    print(f"      [去重] 已记录 {len(papers)} 篇到 last_pushed.json，共累计 {len(pushed_ids | {p['id'] for p in papers})} 篇")


if __name__ == "__main__":
    main()
