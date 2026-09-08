#!/usr/bin/env python3
"""
yhlsd 分析报告 XML 生成脚本
功能：读取分类结果 → 生成飞书文档格式的 XML 报告 → 输出
用法：python3 generate_report.py --input classification.json --output report.xml
"""

import argparse, json, os, re
from datetime import datetime


def clean_text(s):
    """清洗从用户原文里带出来的内容，避免破坏飞书文档 XML。

    用户留言里常混有原始 HTML（如公众号消息里的 <a class=... href=...> 富文本链接），
    直接拼进 XML 会导致未闭合标签把整篇文档 tokenization 打断（2026-09-08 实测踩过：
    block_insert_after 报 partial_success + "XML tokenization error"，报告从三、代表性原问
    处被截断，四五六节全丢）。这里统一做：剥掉 HTML 标签 + 转义 XML 特殊字符。
    """
    s = re.sub(r"<[a-zA-Z][^>]*>", "", s)   # 剥掉 <a ...> <img ...> 等 HTML 标签
    s = re.sub(r"</[a-zA-Z][^>]*>", "", s)  # 剥掉 </a> 等闭合标签
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


PLATFORM_DESCRIPTIONS = {
    "微信公众号": "估值表、指数选择、定投节奏类问题占比最高，公开直播选题价值最大。红利估值口径争议在本渠道最集中，用户常携带第三方平台截图来对质。",
    "企业微信": "组合调仓、定投实操、账户操作类问题更集中。用户语言更口语化/碎片化，但组合机制追问（止盈未触发、不能单独卖）几乎全部来自本渠道。",
    "知识星球": "海外资产、行业主题、进阶策略讨论较多，偏高阶投资者。纳指、标普等海外配置问题占比显著高于其他渠道。",
    "微博": "样本量小但情绪表达强，集中在估值星级和红利争议。",
}


def load_previous(path):
    """Load previous classification data for comparison."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def compute_delta(current, previous):
    """Compute period-over-period deltas for each category."""
    if not previous:
        return {}
    prev_cats = previous.get("category_counts", {})
    cur_cats = current.get("category_counts", {})
    prev_total = previous.get("total_valid", 1) or 1
    cur_total = current.get("total_valid", 1) or 1

    deltas = {}
    for cat in cur_cats:
        cur_val = cur_cats[cat]
        prev_val = prev_cats.get(cat, 0)
        cur_pct = cur_val / cur_total * 100
        prev_pct = prev_val / prev_total * 100 if prev_total else 0
        change = cur_pct - prev_pct
        deltas[cat] = {
            "current_count": cur_val,
            "previous_count": prev_val,
            "current_pct": cur_pct,
            "previous_pct": prev_pct,
            "change_pp": change,  # percentage point change
        }
    return deltas


def generate_xml(data, cut_off_date=None, deltas=None, as_of_date=None):
    total = data["total_valid"]
    cats = data["category_counts"]
    samples = data.get("category_samples", {})
    stats = data.get("stats", {})
    pc = data.get("platform_category", {})

    # as_of_date lets a backfilled/missed-run report be labeled with the date it should
    # have run on, instead of always stamping datetime.now() — without this, re-running a
    # missed Tuesday slot on Thursday mislabels it as the Thursday period (found 2026-08-13).
    today = as_of_date or datetime.now().strftime("%Y-%m-%d")
    if not cut_off_date:
        dd = data.get("date_distribution", {})
        dates = sorted(dd.keys())
        cut_off_date = dates[0] if dates else "unknown"

    has_delta = bool(deltas)

    # ---- 一、数据范围 ----
    # 标题不带"期"字——用户 2026-08-13 明确要求："标题里的期字删除，之后都不要出现，保留日期就可以了"
    xml = f"""<title>AI直播选题分析</title>
<hr/>
<h1>{today}（覆盖 {cut_off_date} ~ {today}）</h1>
<h2>一、数据范围</h2>
<ul>
<li>读取时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}，北京时间</li>
<li>数据来源：yhlsd.com Hub API（微信公众号、知识星球、微博、企业微信）</li>
<li>一次请求拉取全量，有效问题：{total} 条</li>
"""

    for platform in ["微信公众号", "企业微信", "知识星球", "微博"]:
        ps = stats.get(platform, {})
        xml += f"<li>{platform}：{ps.get('valid', 0)} 条（原始 {ps.get('raw', 0)}，剔除 {ps.get('removed', 0)}）</li>\n"

    xml += "</ul>\n<p>已剔除：添加好友提示、账号违规通知、营销推送、直播预告、纯表情、系统消息、无实质短文本（如\"好的\"\"谢谢\"\"收到\"）、主理人本人回复。以下主题采用可重叠统计，数量之和不等于有效问题总数。</p>\n"

    quality_flags = data.get("data_quality_flags", [])
    if quality_flags:
        xml += "<p><b>⚠️ 数据质量提示：</b></p>\n<ul>\n"
        for f in quality_flags:
            xml += f"<li>{f}</li>\n"
        xml += "</ul>\n<p>以上数字仍是脚本能拿到的实际结果，本期分析已生成，但排行占比可能因此偏离真实分布，建议下次执行前先确认 token 是否需要更新。</p>\n"

    # ---- Ranking table with delta ----
    # Note: pre-computed as plain variables rather than inlined in the f-string below —
    # a backslash inside an f-string expression part (e.g. \") is a SyntaxError on
    # Python < 3.12 (only allowed since PEP 701). Keep it this way for portability.
    colspan = 4 if not has_delta else 5
    delta_col = '<col width="100"/>' if has_delta else ""
    delta_th = '<th vertical-align="top"><p>环比变化</p></th>' if has_delta else ""
    xml += f"""<h2>二、高频问题排行（13类分类体系）</h2>
<table>
<colgroup><col width="80"/><col width="300"/><col width="100"/><col width="100"/>{delta_col}</colgroup>
<thead><tr><th vertical-align="top"><p>排名</p></th><th vertical-align="top"><p>主题</p></th><th vertical-align="top"><p>频次</p></th><th vertical-align="top"><p>占比</p></th>{delta_th}</tr></thead>
<tbody>
"""

    top_items = [(k, v) for k, v in cats.items() if k != "其他常见问题"]
    top_items.sort(key=lambda x: x[1], reverse=True)
    for i, (cat, count) in enumerate(top_items[:10], 1):
        pct = count / total * 100 if total else 0
        delta_str = ""
        if has_delta and cat in deltas:
            d = deltas[cat]
            change = d["change_pp"]
            if abs(change) >= 0.5:
                arrow = "↑" if change > 0 else "↓"
                delta_str = f"{arrow} {abs(change):.1f}pp"
            else:
                delta_str = "—"
        xml += f'<tr><td vertical-align="top"><p>{i}</p></td><td vertical-align="top"><p>{cat}</p></td><td vertical-align="top"><p><b>{count}</b></p></td><td vertical-align="top"><p>{pct:.1f}%</p></td>'
        if has_delta:
            xml += f'<td vertical-align="top"><p>{delta_str}</p></td>'
        xml += '</tr>\n'

    other = cats.get("其他常见问题", 0)
    other_pct = other / total * 100 if total else 0
    xml += f'<tr><td vertical-align="top"><p>—</p></td><td vertical-align="top"><p>（其他未归类）</p></td><td vertical-align="top"><p>{other}</p></td><td vertical-align="top"><p>{other_pct:.1f}%</p></td>'
    if has_delta:
        xml += '<td vertical-align="top"><p>—</p></td>'
    xml += '</tr>\n</tbody>\n</table>\n'

    # ---- Representative quotes ----
    xml += "<h2>三、代表性原问</h2>\n<ul>\n"
    for cat, count in top_items[:8]:
        cat_samples = samples.get(cat, [])
        if cat_samples:
            quotes = "；".join([clean_text(s["content"][:180]) for s in cat_samples[:3]])
            xml += f"<li><b>{cat}：</b>{quotes}</li>\n"
    xml += "</ul>\n"

    # 注：之前这里会生成一段"二点五、本期环比信号"，列各分类涨跌最大的几个百分点变化。2026-08-13 用户看到实际
    # 报告后要求去掉（这类环比本身容易受统计口径影响——比如两次运行窗口有重叠、某渠道数据覆盖不稳定，会显得
    # "全线上涨"但其实是假象，容易误导）。deltas 仍然会算出来传给下面的表格环比列和五、六段落用，只是不再单独生成
    # 这个独立小节。

    # ---- Platform differences ----
    xml += "<h2>四、渠道差异</h2>\n<ul>\n"
    for platform in ["微信公众号", "企业微信", "知识星球", "微博"]:
        plat_data = pc.get(platform, {})
        plat_total = stats.get(platform, {}).get("valid", 0)
        if plat_total == 0:
            continue
        desc = PLATFORM_DESCRIPTIONS.get(platform, "")
        top3 = sorted(plat_data.items(), key=lambda x: x[1], reverse=True)
        top3_real = [(k, v) for k, v in top3 if k != "其他常见问题"][:3]
        top3_str = "、".join([f"{k}({v})" for k, v in top3_real])
        xml += f"<li><b>{platform}（{plat_total}条）：</b>{desc} TOP3：{top3_str}</li>\n"
    xml += "</ul>\n"

    # 注：之前这里会插一段"四点五、未归类抽样"到文档里给人工review。2026-08-06 用户在文档里批注要求删除，
    # 不再需要放进正式报告——uncategorized_samples 仍然算出来、仍然在 classify_messages.py 的 stdout WARNING
    # 里打印（脚本执行时能看到），只是不再写进 Feishu 文档正文。

    # ---- 五、用户情绪与需求变化 ----
    xml += f"""<h2>五、用户情绪与需求变化</h2>
<p>[AI 待补充。撰写要求：(1) 至少引用2条本期"三、代表性原问"里出现过的原话作为情绪证据，不要凭空定性；
(2) 如果要提到和上期相比的变化，必须基于"二、高频问题排行"表格里的环比列（如果有）或代表性原问里能看到的实际
变化，不能编造；如果本期没有环比数据就说明"首期无对比基准"。不要机械罗列"XX类别涨了X个百分点"这种排行榜式的
环比清单（2026-08-13 用户明确要求去掉这种"二点五、本期环比信号"式的展示——这类清单容易被统计口径的假象带偏，
比如两次运行窗口有重叠、某渠道数据覆盖不稳定导致"看起来全线上涨"，实际不是真实的关注度变化）；(3) 类别环比
变化 &lt;1pp 的，如实写"保持稳定"，禁止为了内容丰满而夸大成"显著变化"。]</p>

<h2>六、建议直播选题</h2>
<p>[AI 待补充 5 个选题方向（用户 2026-08-06 明确要求 5 个，3个太少，不要减少）。每个选题必须包含：优先级（高优/中优）、
选题理由（对应哪个高频分类 + 具体频次或环比数字支撑，不能只写"用户关心"这种空话）、核心问题（要正面回应的1-2个具体
用户疑问，最好直接引用原文）、建议结构（3-4步的内容框架）。禁止逐字复用上一期已经发布过的选题方向——如果某个方向
本期依然成立，必须结合本期新数据换一个新角度或新案例。5个选题是并列独立的候选项，供老板挑选，不是要串成一个系列——
不要在列表后面加"选题串联逻辑"或任何暗示几个选题要连起来做的总结段落（用户 2026-08-06 明确要求去掉）。]</p>
"""

    return xml


def main():
    parser = argparse.ArgumentParser(description="Generate Feishu doc XML report")
    parser.add_argument("--input", required=True, help="Path to classification JSON")
    parser.add_argument("--previous", default=None, help="Path to previous classification JSON for delta comparison")
    parser.add_argument("--output", required=True, help="Output XML path")
    parser.add_argument("--as-of", default=None,
                         help="YYYY-MM-DD to label the report with, instead of today. Use this when backfilling "
                              "a missed scheduled run (e.g. running Tuesday's slot on Thursday) so the report "
                              "isn't mislabeled with today's date.")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    previous = load_previous(args.previous)
    deltas = compute_delta(data, previous) if previous else None

    xml = generate_xml(data, deltas=deltas, as_of_date=args.as_of)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(xml)

    print(f"Report generated: {args.output} ({len(xml)} chars)")
    if deltas:
        print(f"  Delta comparison: enabled ({len(deltas)} categories)")


if __name__ == "__main__":
    main()
