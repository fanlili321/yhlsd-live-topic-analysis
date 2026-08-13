#!/usr/bin/env python3
"""
yhlsd 留言清洗与分类脚本
功能：加载原始JSON → 剔除无效 → 按13类关键词分类 → 输出分类结果
用法：python3 classify_messages.py --input /tmp/yhlsd_automation/messages_raw.json --output /tmp/yhlsd_automation/classification.json
"""

import argparse, json, os, sys, re
from collections import Counter

CATEGORIES_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "categories.md")

_HEADER_RE = re.compile(r"^### \d+\.\s*(.+?)\s*(?:\((.*?)\))?\s*$")
_KEYWORDS_RE = re.compile(r"^\-\s*\*\*关键词：\*\*\s*(.+)$")


def load_categories(path=CATEGORIES_MD):
    """Parse the '### N. 类别名 (权重 X)' / '- **关键词：** a、b、c' structure out of
    categories.md so it stays the single source of truth for keyword lists."""
    categories = {}
    current = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("---"):
                current = None
                continue
            m = _HEADER_RE.match(line)
            if m:
                name, paren = m.group(1), m.group(2) or ""
                weight_m = re.search(r"权重\s*([\d.]+)", paren)
                current = name
                categories[current] = {"keywords": [], "weight": float(weight_m.group(1)) if weight_m else 1.0}
                continue
            if current:
                km = _KEYWORDS_RE.match(line)
                if km:
                    kws = [k.strip() for k in km.group(1).split("、") if k.strip()]
                    categories[current]["keywords"] = kws
    if "其他常见问题" not in categories:
        categories["其他常见问题"] = {"keywords": [], "weight": 1.0}
    return categories


CATEGORIES = load_categories()

# ---- Noise filters ----
HOST_KEYWORDS = ["钉大", "螺丝钉", "银行螺丝钉", "主理人"]
BAN_KEYWORDS = [
    "账号违规", "功能已被限制", "添加好友", "加好友", "查看详情",
    # 企业微信自动生成的系统提示，不是用户内容——2026-08-06 用真实数据核查时发现这是
    # 企业微信渠道"其他"占比虚高的主要来源之一
    "我已经添加了你，现在我们可以开始聊天了", "你已添加了", "微信授权已过期",
    "离开了群聊", "加入了群聊", "移出了群聊",
    # 官方周报广播，不是客户提问——2026-08-06 用真实数据核查时发现这条被误判为用户内容，
    # 原因是上游数据里这条记录的 is_question 字段标反了，导致主理人过滤没生效，只能按内容再兜一次底
    "螺丝钉学院周报",
    # 2026-08-13 第二周真实数据核查时新发现的系统消息/官方广播模式
    "以上是打招呼内容",  # 企业微信待通过好友申请的自动提示
    "指数阈值表来啦",  # 知识星球每日估值表推送广播
]
SHORT_NOISE = {"好的", "谢谢", "收到", "嗯", "哦", "ok", "OK", "1", "。", "?", "？"}
# 纯祝福/寒暄，没有实质问题或反馈，2026-08-06 真实数据里高频出现
BLESSING_NOISE = ["周末愉快", "静待花开", "早安", "晚安", "新年快乐"]
PROMO_KEYWORDS = ["直播预告", "营销"]
_BRACKET_EMOJI_RE = re.compile(r"\[[^\[\]]{1,6}\]")
_TRACKING_LOG_RE = re.compile(r"^\d+\s*观看直播\d*$")
# 直播报名/登记的追踪码或按钮文案，纯数字/短标签拼接，不是用户写的内容
# （如 "直播 登记"、"260804 26804"、"直播课 060804"、"260811 丁大老师直播发我"、"往期直播 220729"）
# ——2026-08-06、2026-08-13 两周真实数据核查时发现。注意这是"整条内容只有数字+这些标签词"才算噪音，
# 不是简单按关键词子串禁掉，所以"麻烦把往期直播发我一下"这种带真实语气的句子不会被误伤（正则要求 ^...$ 全匹配）。
_REGISTRATION_LOG_RE = re.compile(r"^[\d\s]*(?:(?:直播课?|登记|新人|丁大老师|直播发我|往期直播)[\d\s]*)*$")


def is_host_reply(msg):
    """Filter out replies from the host (钉大/螺丝钉)."""
    content = msg.get("content", "")
    floor_type = msg.get("floor_type", "")
    floor_path = msg.get("floor_path", "")

    if "客户留言" in floor_type or "客户" in floor_path:
        return False
    if not msg.get("is_question", False):
        for kw in HOST_KEYWORDS:
            if kw in content:
                return True
    return False


def is_noise(msg):
    """Filter out noise: bans, emojis, one-word replies, promos, blessings, tracking logs."""
    content = msg.get("content", "").strip()

    for kw in BAN_KEYWORDS:
        if kw in content:
            return True
    if len(content) <= 3 and content in SHORT_NOISE:
        return True
    if len(content) <= 2 and not any("\u4e00" <= c <= "\u9fff" for c in content):
        return True
    for kw in PROMO_KEYWORDS:
        if kw in content:
            return True
    for kw in BLESSING_NOISE:
        if kw in content:
            return True
    if _TRACKING_LOG_RE.match(content):
        return True
    if _REGISTRATION_LOG_RE.match(content):
        return True
    # \u53bb\u6389\u6240\u6709 [\u8868\u60c5] \u6807\u8bb0\u540e\u5982\u679c\u5269\u4e0b\u7684\u5185\u5bb9\u4e5f\u662f\u77ed\u566a\u97f3\uff0c\u8bf4\u660e\u6574\u6761\u5c31\u662f\u7eaf\u8868\u60c5\u5806\u780c
    # \uff08\u5982 "[\u8d5e][\u8d5e][\u8d5e]"\u3001"[good][good][good]"\uff09\uff0c\u6309\u566a\u97f3\u5904\u7406
    stripped = _BRACKET_EMOJI_RE.sub("", content).strip()
    if content != stripped and (not stripped or (len(stripped) <= 3 and stripped in SHORT_NOISE)):
        return True
    return False


def is_valid_question(msg):
    """Check if message is worth classifying."""
    if is_noise(msg):
        return False
    if is_host_reply(msg):
        return False
    if len(msg.get("content", "").strip()) < 5:
        return False
    return True


def classify_one(content, categories):
    """Classify a single message, returns list of matching category names."""
    matched = []
    for cat, config in categories.items():
        if cat == "其他常见问题":
            continue
        score = 0
        for kw in config.get("keywords", []):
            if kw in content:
                score += 1
            elif re.search(kw, content):
                score += 1
        if score > 0:
            weight = config.get("weight", 1.0)
            matched.append((cat, score * weight))
    return matched


def main():
    parser = argparse.ArgumentParser(description="Clean and classify yhlsd messages")
    parser.add_argument("--input", required=True, help="Path to raw messages JSON")
    parser.add_argument("--output", required=True, help="Output classification JSON path")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)

    messages_by_platform = raw.get("messages", raw)  # support both wrapped and plain format

    # ---- Clean ----
    clean_stats = {}
    all_valid = {}

    for platform, msgs in messages_by_platform.items():
        if not isinstance(msgs, list):
            continue
        valid = [m for m in msgs if is_valid_question(m)]
        clean_stats[platform] = {
            "raw": len(msgs),
            "valid": len(valid),
            "removed": len(msgs) - len(valid),
        }
        all_valid[platform] = valid
        print(f"{platform}: {len(msgs)} → {len(valid)} valid ({len(msgs)-len(valid)} removed)")

    total_valid = sum(s["valid"] for s in clean_stats.values())
    print(f"\nTotal valid questions: {total_valid}")

    # ---- Classify ----
    category_counts = Counter()
    category_samples = {cat: [] for cat in CATEGORIES}
    platform_category = {}
    uncategorized_samples = []  # feedback loop: what's slipping through the 13 categories

    for platform, msgs in all_valid.items():
        platform_category[platform] = Counter()
        for m in msgs:
            content = m.get("content", "")
            matched = classify_one(content, CATEGORIES)
            if matched:
                for cat, score in matched:
                    category_counts[cat] += 1
                    platform_category[platform][cat] += 1
                best = max(matched, key=lambda x: x[1])[0]
                if len(category_samples.get(best, [])) < 3:
                    category_samples[best].append({
                        "content": content[:200],
                        "platform": platform,
                        "user": m.get("user_name", ""),
                        "date": m.get("created_at", "")[:10],
                    })
            else:
                category_counts["其他常见问题"] += 1
                platform_category[platform]["其他常见问题"] += 1
                if len(uncategorized_samples) < 30:
                    uncategorized_samples.append({
                        "content": content[:200],
                        "platform": platform,
                        "date": m.get("created_at", "")[:10],
                    })

    # Sort results
    sorted_cats = category_counts.most_common()

    print("\n=== TOP 10 Categories ===")
    for i, (cat, count) in enumerate(sorted_cats[:10], 1):
        pct = count / total_valid * 100 if total_valid else 0
        print(f"  {i}. {cat}: {count} ({pct:.1f}%)")

    other_count = category_counts.get("其他常见问题", 0)
    other_pct = other_count / total_valid * 100 if total_valid else 0
    if other_pct >= 35:
        print(f"\nWARNING: “其他常见问题”占比 {other_pct:.1f}%（{other_count}/{total_valid}），"
              f"分类关键词覆盖不足。查看 output 里的 uncategorized_samples，"
              f"人工review后把重复出现的问法加进 references/categories.md 对应类别。")

    # Save
    output = {
        "total_valid": total_valid,
        "stats": clean_stats,
        "category_counts": dict(sorted_cats),
        "category_samples": {k: v for k, v in category_samples.items() if v},
        "uncategorized_samples": uncategorized_samples,
        "uncategorized_pct": round(other_pct, 1),
        "platform_category": {k: dict(v) for k, v in platform_category.items()},
        "date_distribution": raw.get("date_distribution", {}),
        "data_quality_flags": raw.get("data_quality_flags", []),
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
