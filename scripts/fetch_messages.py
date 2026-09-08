#!/usr/bin/env python3
"""
yhlsd.com 留言全量拉取脚本（Hub API v2）
功能：通过 Bearer token 调用 /hub/api/messages，按 days 过滤，一把拉取全量留言
用法：python3 fetch_messages.py [--days 4] [--output /tmp/messages.json] [--token TOKEN]
（--days 默认4天，是固定规则，见下面 argparse 里的注释，不要改成7天）

Token 获取方式：飞书扫码登录 https://qa.yhlsd.com/hub/ 后获取 AI 接口 token
也可通过环境变量 YHLSD_API_TOKEN 传入
"""

import argparse, json, os, sys
from datetime import datetime, timedelta
from collections import Counter

BASE = "http://qa.yhlsd.com"
API_PATH = "/hub/api/messages"
DEFAULT_TOKEN = "26e5637a4ebc27256b7ba736e9fdb1c5436ebb70988273b793638868455273ec"  # 更新于 2026-08-13

PLATFORMS = ["微信公众号", "知识星球", "微博", "企业微信"]

# 上游平台名 → 归并到四个标准渠道。2026-09-08 发现上游新增了两个平台名：
# 「雪球企微钉友会群」（企业微信下的雪球钉友会群）、「公众号私信」（微信公众号的私信消息），
# 之前没在 PLATFORMS 里，被当成 unknown platform 直接跳过、丢失了。这里做别名映射归并，
# 避免再出现"新渠道数据被静默丢弃"的情况。上游平台全列表以 /hub/api/platforms 为准，
# 以后上游再加新平台，优先到这里补别名。
PLATFORM_ALIASES = {
    "雪球企微钉友会群": "企业微信",
    "公众号私信": "微信公众号",
}

# Rough baselines for a 7-day window (scaled for other windows below), used only to
# flag suspiciously low counts — e.g. a platform-side page cap silently returning
# fewer rows than requested with a 200 OK, instead of erroring like a dead token would.
# Not a hard validation gate, just a loud warning so a silent truncation doesn't
# quietly poison the report with numbers that look plausible but aren't.
BASELINE_MIN_7D = {
    "企业微信": 1000,
    "知识星球": 300,
    "微信公众号": 60,
    "微博": 20,
}
SUSPICIOUS_ROUND_NUMBERS = {500, 1000, 2000, 5000}


def fetch_all(token, days, limit=5000):
    """Fetch all messages within N days via hub API."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"days": days, "limit": limit}
    url = f"{BASE}{API_PATH}"

    print(f"=== Fetching messages (days={days}, limit={limit}) ===")
    r = requests.get(url, params=params, headers=headers, timeout=120)
    
    if r.status_code == 401:
        print("ERROR: 未授权。请在 https://qa.yhlsd.com/hub/ 飞书扫码登录后获取新 token")
        sys.exit(1)
    elif r.status_code != 200:
        print(f"ERROR: HTTP {r.status_code} - {r.text[:300]}")
        sys.exit(1)

    data = r.json()
    count = data.get("count", 0)
    items = data.get("items", [])
    print(f"  Response: count={count}, items={len(items)}")

    if count < limit:
        print(f"  → 全量数据，无需翻页")
    else:
        print(f"  → count 等于 limit({limit})，可能有截断，建议调高 limit")

    return items


def split_by_platform(items):
    """Split flat item list into per-platform dicts."""
    by_platform = {p: [] for p in PLATFORMS}
    for m in items:
        p = m.get("platform", "")
        p = PLATFORM_ALIASES.get(p, p)  # 别名归并（如"雪球企微钉友会群"→"企业微信"）
        if p in by_platform:
            by_platform[p].append(m)
        else:
            print(f"  WARNING: unknown platform '{p}', skipping")
    return by_platform


def deduplicate(messages_by_platform):
    """Remove duplicate messages by id within each platform."""
    for platform, msgs in messages_by_platform.items():
        seen = set()
        unique = []
        for m in msgs:
            mid = m.get("id", "")
            if mid not in seen:
                seen.add(mid)
                unique.append(m)
        dups = len(msgs) - len(unique)
        print(f"  {platform}: {len(msgs)} raw → {len(unique)} unique (removed {dups} dups)")
        messages_by_platform[platform] = unique
    return messages_by_platform


def main():
    parser = argparse.ArgumentParser(description="Fetch yhlsd.com messages via Hub API")
    # 默认4天，不是7天——用户2026-08-13明确定为固定规则："每次覆盖的都是四天，不要随意改变"。
    # 周二/周四14:00各跑一次，两次窗口本来就会有重叠（周四→周二间隔5天，周二→周四间隔2天，
    # 固定4天窗口不会精确贴合这个不对称的间隔），这是用户接受的规则，不要因为"看起来该按日历对齐"就改成动态天数。
    parser.add_argument("--days", type=int, default=4, help="Number of days to look back (固定4天，见上面注释)")
    parser.add_argument("--output", type=str, default="/tmp/yhlsd_automation/messages_raw.json")
    parser.add_argument("--token", type=str, default=None, help="API token (or set YHLSD_API_TOKEN env)")
    parser.add_argument("--limit", type=int, default=5000, help="Max items per request (上限5000)")
    args = parser.parse_args()

    token = args.token or os.environ.get("YHLSD_API_TOKEN") or DEFAULT_TOKEN
    if token == DEFAULT_TOKEN:
        print("WARNING: 使用内置 token。如需更换，用 --token 参数或设置 YHLSD_API_TOKEN 环境变量\n")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"时间范围: {cutoff} ~ 今天 ({args.days} 天)")

    # Step 1: Fetch all via hub API
    items = fetch_all(token, args.days, args.limit)

    # Step 2: Apply date cutoff (API days may include extra)
    recent = [m for m in items if m.get("created_at", "")[:10] >= cutoff]
    print(f"\n=== 日期过滤 ===\n  全量 {len(items)} → {len(recent)} (截止 {cutoff})")

    # Step 3: Split by platform
    all_msgs = split_by_platform(recent)

    # Step 4: Deduplicate
    print("\n=== 去重 ===")
    all_msgs = deduplicate(all_msgs)

    # Step 5: Summary
    total = sum(len(v) for v in all_msgs.values())
    print(f"\n=== 汇总: {total} 条 ===")
    quality_flags = []
    for platform in PLATFORMS:
        cnt = len(all_msgs.get(platform, []))
        questions = sum(1 for m in all_msgs.get(platform, []) if m.get("is_question"))
        print(f"  {platform}: {cnt} 条 (提问 {questions})")

        baseline = BASELINE_MIN_7D.get(platform)
        if baseline:
            scaled_baseline = baseline * args.days / 7
            if cnt < scaled_baseline:
                msg = (f"{platform} 原始条数 {cnt} 低于 {args.days} 天窗口的预期基线 "
                       f"~{scaled_baseline:.0f} 条，可能是 token 权限受限、平台数据源异常，"
                       f"或 API 存在未在响应里报告的分平台截断")
                quality_flags.append(msg)
        if cnt in SUSPICIOUS_ROUND_NUMBERS:
            msg = (f"{platform} 原始条数恰好等于 {cnt}（常见的分页/单平台上限整数），"
                   f"疑似被截断而非真实全量——如果这个数字每次都精确重复出现，基本可以确认是截断")
            quality_flags.append(msg)
    if quality_flags:
        print("\n=== 数据质量警告 ===")
        for f in quality_flags:
            print(f"  WARNING: {f}")

    # Date distribution
    date_dist = Counter()
    for msgs in all_msgs.values():
        for m in msgs:
            d = m.get("created_at", "")[:10]
            date_dist[d] += 1
    print(f"\n日期分布:")
    for d in sorted(date_dist.keys()):
        print(f"  {d}: {date_dist[d]}")

    # Step 6: Save
    output = {
        "fetch_time": datetime.now().isoformat(),
        "cutoff_date": cutoff,
        "days": args.days,
        "messages": all_msgs,
        "date_distribution": dict(sorted(date_dist.items())),
        "data_quality_flags": quality_flags,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"\n保存至 {args.output}")


if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        print("ERROR: 需安装 requests 库: pip install requests")
        sys.exit(1)
    main()
