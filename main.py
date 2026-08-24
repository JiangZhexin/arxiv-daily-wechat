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

# 单条模板消息里放几篇论文（改版后每条 1 篇，以便完整展示中英文摘要）
PAPERS_PER_MESSAGE = 1

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
    hours_back = int(os.environ.get("ARXIV_HOURS_BACK") or arxiv_cfg.get("hours_back", 60))
    max_papers_per_run = int(os.environ.get("ARXIV_MAX_PAPERS") or arxiv_cfg.get("max_papers_per_run", 8))

    ds_cfg = cfg.get("deepseek", {})
    deepseek = {
        "api_key": os.environ.get("DEEPSEEK_API_KEY") or ds_cfg.get("api_key", ""),
        "base_url": os.environ.get("DEEPSEEK_BASE_URL") or ds_cfg.get("base_url", "https://api.deepseek.com"),
        "model": os.environ.get("DEEPSEEK_MODEL") or ds_cfg.get("model", "deepseek-chat"),
    }

    wx_cfg = cfg.get("wechat", {})
    fields = dict(DEFAULT_TEMPLATE_FIELDS)
    fields.update(wx_cfg.get("template_fields", {}))
    wechat = {
        "app_id": os.environ.get("WECHAT_APP_ID") or wx_cfg.get("app_id", ""),
        "app_secret": os.environ.get("WECHAT_APP_SECRET") or wx_cfg.get("app_secret", ""),
        "template_id": os.environ.get("WECHAT_TEMPLATE_ID") or wx_cfg.get("template_id", ""),
        "user_openid": os.environ.get("WECHAT_OPENID") or wx_cfg.get("user_openid", ""),
        "template_fields": fields,
    }

    return {"arxiv": {"categories": categories, "hours_back": hours_back}, "deepseek": deepseek, "wechat": wechat}


def _category_label(primary: str) -> str:
    return CATEGORY_NAMES.get(primary, primary)


def build_messages(papers, summaries, template_fields, categories, date_str):
    """
    把论文列表 + 总结整理成模板消息。每篇论文一条消息，含一句话总结 + 中英文摘要。

    返回: list[dict]，每个 dict:
        {"data": {模板字段: {...}}, "url": "论文 arxiv 链接（点击消息可跳转）"}
    """
    category_text = "、".join(_category_label(c) for c in categories)
    first_text = "📚 arXiv 每日论文速览"
    keyword1_text = category_text
    keyword2_text = f"今日新增 {len(papers)} 篇"
    keyword3_text = date_str

    f, k1, k2, k3, r = (
        template_fields["first"],
        template_fields["keyword1"],
        template_fields["keyword2"],
        template_fields["keyword3"],
        template_fields["remark"],
    )

    messages = []
    for p in papers:
        info = summaries.get(p["id"], {})
        title_zh = info.get("title_zh") or p["title"]
        one_line = info.get("summary") or "（未生成总结）"
        # 英文摘要：直接用 arXiv 原文（截断控制长度）
        abstract_en = p["summary"][:220] + ("…" if len(p["summary"]) > 220 else "")
        # 中文摘要：DeepSeek 生成的中文翻译
        abstract_zh = info.get("abstract_zh") or "（未生成翻译）"
        label = _category_label(p["primary"])

        remark_text = (
            f"[{p['id']}] {title_zh}（{label}）\n"
            f"💡 {one_line}\n\n"
            f"【EN Abstract】\n{abstract_en}\n\n"
            f"【中文摘要】\n{abstract_zh}"
        )
        # 单条 remark 限长保护（微信模板消息字段上限约 600 字符）
        if len(remark_text) > 600:
            remark_text = remark_text[:590] + "…（内容过长已截断）"

        messages.append(
            {
                "data": {
                    f: {"value": first_text},
                    k1: {"value": keyword1_text},
                    k2: {"value": keyword2_text},
                    k3: {"value": keyword3_text},
                    r: {"value": remark_text},
                },
                "url": p["url"],
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
    print(f"      共抓到 {len(papers)} 篇")

    # 单次最多推送 max_papers_per_run 篇，防止论文特别多时微信刷屏
    if len(papers) > max_papers_per_run:
        print(f"      [提示] 论文较多，本次仅推送最新的 {max_papers_per_run} 篇（可调大 max_papers_per_run）")
        papers = papers[:max_papers_per_run]

    if not papers:
        print("[完成] 今天没有新论文，不推送。")
        return

    # 2) 总结
    print(f"[2/3] 调用 DeepSeek（{ds_cfg['model']}）生成中文总结 ...")
    summaries = summarize_papers(papers, api_key=ds_cfg["api_key"], base_url=ds_cfg["base_url"], model=ds_cfg["model"])
    print(f"      成功总结 {len(summaries)}/{len(papers)} 篇")

    # 3) 组织消息
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    messages = build_messages(papers, summaries, wx_cfg["template_fields"], arxiv_cfg["categories"], date_str)
    print(f"[3/3] 共组织 {len(messages)} 条微信模板消息（每条最多 {PAPERS_PER_MESSAGE} 篇论文）")

    if args.dry_run:
        print("\n================  dry-run 预览 ================")
        for idx, msg in enumerate(messages, 1):
            print(f"\n----- 消息 {idx}  |  点击跳转: {msg['url']} -----")
            for k, v in msg["data"].items():
                print(f"{k}: {v['value']}")
        print("\n[dry-run] 仅预览，未发送微信。")
        return

    # 4) 推送
    pusher = WeChatPusher(wx_cfg["app_id"], wx_cfg["app_secret"], wx_cfg["template_id"], wx_cfg["user_openid"])
    sent = pusher.send_batch(messages)
    print(f"[完成] 已发送 {sent} 条消息到微信，公众号: 测试号")


if __name__ == "__main__":
    main()
