# -*- coding: utf-8 -*-
"""wait_until.py —— 等到指定北京时间再继续，用来抵消 GitHub schedule 的触发延迟。

背景：
  GitHub Actions 的 schedule 不保证准时，实测本仓库的定时任务会比设定时间
  晚 2~5 小时触发。与其被它牵着走，不如反过来利用：
    把 cron 设在「一定早于目标时间」的位置，任务触发后先睡到目标时刻再干活。
  这样无论 GitHub 延迟多久（只要不超过 sleep 上限），推送都落在同一时刻。

用法:
    python tools/wait_until.py            # 默认等到北京时间 12:25
    python tools/wait_until.py 09:00      # 等到北京时间 09:00
    python tools/wait_until.py 12:25 --max-wait 240
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))
DEFAULT_AT = "12:25"
DEFAULT_MAX_WAIT_MIN = 240


def parse_at(text):
    """把 "HH:MM" 解析成 (hour, minute)。"""
    parts = str(text or "").strip().split(":")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise SystemExit(f"[错误] 时间格式应为 HH:MM（北京时间），收到: {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit(f"[错误] 时间超出范围: {text!r}")
    return hour, minute


def main():
    parser = argparse.ArgumentParser(description="等到指定北京时间再继续")
    parser.add_argument("at", nargs="?", default=DEFAULT_AT, help=f"北京时间 HH:MM（默认 {DEFAULT_AT}）")
    parser.add_argument("--max-wait", type=float, default=DEFAULT_MAX_WAIT_MIN,
                        help=f"最多等多少分钟，超过就不等了（默认 {DEFAULT_MAX_WAIT_MIN}）")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    hour, minute = parse_at(args.at)
    now = datetime.now(BEIJING)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    print(f"[守时] 当前北京时间 {now:%Y-%m-%d %H:%M:%S}（UTC {datetime.now(timezone.utc):%H:%M:%S}）")
    print(f"[守时] 目标推送时刻 北京时间 {target:%Y-%m-%d %H:%M}")

    if now >= target:
        print("[守时] 已经过了目标时刻，立即开始（说明 GitHub 调度延迟超出预期）")
        return

    wait_seconds = (target - now).total_seconds()
    if wait_seconds > args.max_wait * 60:
        print(f"[守时] 需要等待 {wait_seconds/60:.1f} 分钟，超过上限 {args.max_wait:.0f} 分钟，放弃等待立即开始")
        return

    print(f"[守时] 等待 {wait_seconds/60:.1f} 分钟，到 {target:%H:%M} 再抓取并推送（保证取到最新论文）")
    # 分段 sleep，顺便定期打印心跳，避免日志看起来像卡死
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        chunk = min(remaining, 300)
        time.sleep(chunk)
        remaining = deadline - time.monotonic()
        if remaining > 30:
            print(f"[守时] 还剩 {remaining/60:.1f} 分钟 ...")
    print(f"[守时] 到时，开始抓取（北京时间 {datetime.now(BEIJING):%H:%M:%S}）")


if __name__ == "__main__":
    main()
