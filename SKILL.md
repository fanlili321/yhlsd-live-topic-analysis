---
name: yhlsd-live-topic-analysis
description: 银行螺丝钉直播选题分析工具。从 yhlsd.com 拉取微信公众号、知识星球、微博、企业微信的全量客户留言，按13类分类体系清洗分析高频问题，生成选题报告更新飞书文档，并通过飞书消息推送摘要。用于直播前的高频问题分析和选题规划。
agent_created: true
---

# yhlsd 直播选题分析

## 概述

从 yhlsd.com 客户互动中枢（https://qa.yhlsd.com/hub/）通过 Hub API 拉取近期客户留言，按13类关键词分类识别高频问题，生成分析报告写入飞书文档并推送消息摘要。用于银行螺丝钉直播前的选题规划。

## 工作流

整个流程按4步执行，每步完成后确认结果再继续。**执行第1步之前，先做一次 git pull（见下）。**

### 第0步：同步最新代码（git pull）

这个 skill 的源码托管在私有仓库 `https://github.com/fanlili321/yhlsd-live-topic-analysis`（2026-08-13 起），
本地目录 `~/.workbuddy/skills/yhlsd-live-topic-analysis` 是一个软链接，指向的真实目录
`~/Desktop/范丽丽./自动化备份/workbuddy/yhlsd-live-topic-analysis-skill/` 是这个仓库的本地 clone。
**每次执行前先拉一下最新代码**，这样如果规则在网页上被改过（或者其他协作者改过），能自动生效，不需要再手动
zip 备份同步：

```bash
cd ~/.workbuddy/skills/yhlsd-live-topic-analysis && git pull --ff-only
```

如果 `git pull` 失败（比如本地有未提交的改动导致冲突），**不要用 `git reset --hard`/`git checkout .` 之类的
方式强行覆盖本地改动**——先看一下 `git status`，本地改动可能是还没来得及提交的正常工作内容。遇到这种情况就
跳过 pull，正常往下执行，并在完成后的通知里提一句"本次跳过了 git pull，本地有未提交改动"，让人来处理，不要
自己尝试解决冲突。

### 第1步：拉取全量留言

使用 `scripts/fetch_messages.py` 拉取数据：

```bash
cd /tmp && python3 ~/.workbuddy/skills/yhlsd-live-topic-analysis/scripts/fetch_messages.py --days 4 --output /tmp/yhlsd_automation/messages_raw.json
```

**`--days 4` 是固定规则，不要改成 7 或其他值。** 用户 2026-08-13 明确要求："每次覆盖的都是四天，这是规则，不要随意改变"。
周二、周四各跑一次，两次固定4天窗口之间会有重叠（周四→下周二间隔5天，周二→周四间隔2天，4天窗口不会精确对齐这个
不对称间隔），这是用户接受的规则，不要"觉得应该按日历对齐"就擅自改成动态天数。脚本参数默认值已经是4。

脚本自动：
- 通过 Bearer token 调用 `GET /hub/api/messages`，一次请求拉取全量留言（limit=5000 上限）
- 按 `days` 参数过滤日期范围
- 按四个平台（微信公众号/知识星球/微博/企业微信）分组
- 按消息 ID 去重
- 输出日期分布统计

**Token 配置：** 飞书扫码登录 https://qa.yhlsd.com/hub/ 获取 AI 接口 token，通过 `--token` 参数或环境变量 `YHLSD_API_TOKEN` 传入。脚本内置默认 token。

**验证数据量：** 4天窗口企业微信实测大约 600-750 条（2026-08-13 当周两次实测分别为 738、675），远低于此可能 token 失效或 API 异常。
（这个基线是按4天窗口重新校准的，如果哪天又改回7天窗口，基线也要跟着换算，别直接套用这个数字。）

不再需要 `NO_PROXY` 和分页循环，新 Hub API 一次请求即可。

### 第2步：清洗与分类

```bash
cd /tmp && python3 ~/.workbuddy/skills/yhlsd-live-topic-analysis/scripts/classify_messages.py --input /tmp/yhlsd_automation/messages_raw.json --output /tmp/yhlsd_automation/classification.json
```

脚本自动执行：
- 剔除主理人回复（钉大/螺丝钉）、账号违规通知、营销推送、纯表情、无意义短文本
- 按13类关键词分类（可重叠），详见 `references/categories.md`
- 输出：各平台清洗统计、分类频次排行、代表性原问样本、渠道差异

### 第3步：生成报告并更新飞书文档

先运行脚本生成 XML 骨架：

```bash
cd /tmp && python3 ~/.workbuddy/skills/yhlsd-live-topic-analysis/scripts/generate_report.py --input /tmp/yhlsd_automation/classification.json --output /tmp/yhlsd_automation/report.xml
```

然后**手动补全**报告中「五、用户情绪与需求变化」和「六、建议直播选题」两个部分，基于分类数据做定性分析和选题推荐。

最后插入飞书文档（**只增不删，使用 block_insert_after**）：

```bash
# 1. 拉取文档含 block ID（当前 lark-cli 1.0.84 返回的是一整段 content 字符串，
#    每个标签内联 id="..." 属性，不是 blocks 数组——2026-08-06 用真实数据跑通时确认过）
lark-cli docs +fetch --doc KsInd8S1ko6jQgxlypncNcqanPe --detail with-ids > /tmp/doc_with_ids.json

# 2. 从 content 字符串开头解析出 title 的 id（<title id="...">），在它之后插入分隔线 + 新报告
python3 -c "
import json, re
with open('/tmp/doc_with_ids.json') as f:
    content = json.load(f)['data']['document']['content']
title_id = re.match(r'<title id=\"([^\"]+)\"', content).group(1)
with open('/tmp/yhlsd_automation/report.xml') as f:
    report = f.read()
combined = '<hr/><hr/>' + report
with open('/tmp/yhlsd_automation/insert_content.xml', 'w') as f:
    f.write(combined)
print('title_id:', title_id)
"

# 3. 用 stdin 传内容（--content 只接受相对路径的 @file 或 - 读 stdin，不接受绝对路径 @file）
cat /tmp/yhlsd_automation/insert_content.xml | lark-cli docs +update --doc KsInd8S1ko6jQgxlypncNcqanPe \
  --command block_insert_after --block-id <title_id> --content -
```

（实测中 title block 的 block_id 恰好等于文档 token 本身，但不要依赖这个巧合，还是从 content 里现解析。）

报告格式规范详见 `references/report_format.md`。

**关键约束：**
- 文档 Token：`KsInd8S1ko6jQgxlypncNcqanPe`
- 倒序排列（最新一期在最前面）
- 每期报告用六段式结构（数据范围→高频排行→代表性原问→渠道差异→情绪变化→选题建议）
- **只增不删**：使用 `block_insert_after` 在 title 块后插入，**绝不 overwrite**，已有内容永远不动

### 第4步：发送飞书通知

**只发一句"执行完毕 + 文档链接"，不要发长摘要。** 用户 2026-08-06 明确要求："执行完毕后通知我，告诉我执行完毕就
可以，不需要对我发很长的话了，直接把链接发给我就行"。之前这里是一大段带 TOP3/选题建议/emoji 的摘要，已经废弃。

```bash
lark-cli im +messages-send --chat-id oc_94c21bc74eb7413a61c4647ca15a78ea --text "【AI直播选题分析】{日期范围} 已更新：https://epndqwwg0a.feishu.cn/docx/KsInd8S1ko6jQgxlypncNcqanPe"
```

## 关键资源

| 资源 | 用途 |
|------|------|
| `scripts/fetch_messages.py` | Hub API 拉取（Bearer token，一次请求全量，含数据量异常检测）|
| `scripts/classify_messages.py` | 清洗 + 13 类关键词分类（关键词从 `categories.md` 动态解析，含"其他"桶抽样）|
| `scripts/generate_report.py` | 生成飞书文档 XML 骨架（含数据质量提示、未归类抽样、五/六段落的撰写规则）|
| `references/categories.md` | **13 类关键词与清洗规则的唯一数据源**，`classify_messages.py` 直接解析这个文件 |
| `references/report_format.md` | 文档结构规范 + 消息格式 |

## 注意事项

1. **Hub API 一次拉取全量。** 使用 `GET /hub/api/messages?days=N&limit=5000`，不再需要分页和 sync。
2. **必须剔除主理人回复。** 钉大/螺丝钉的回复如果混入统计，会把组合调仓等类别虚高。
3. **分类可重叠。** 一条留言可命中多个类别，数量之和不等于有效问题总数。
4. **Token 到期需更新。** 飞书扫码登录 https://qa.yhlsd.com/hub/ 重新获取，更新脚本中 `DEFAULT_TOKEN` 或传入 `--token`。401 会直接报错退出，
   但如果某个平台返回 200 却只给了截断数据（见下一条），脚本不会自动报错，需要看数据质量提示。
5. **数据量异常检测。** `fetch_messages.py` 会对比 `BASELINE_MIN_7D` 里的历史基线，如果某平台原始条数明显偏低，
   或者恰好等于 500/1000/2000/5000 这类可疑整数（很可能是分平台截断而不是真实全量），会打印 WARNING 并写进
   `data_quality_flags`，`generate_report.py` 会把这些提示直接放进文档正文的「一、数据范围」里，不会被悄悄忽略。
6. **关键词只改 `references/categories.md` 一处。** `classify_messages.py` 不再自己维护第二份关键词字典，改完
   `categories.md` 直接重跑分类脚本就会生效。新增关键词前参考 `categories.md` 底部"已知的关键词精度注意事项"，
   避免再出现"银行"命中"银行螺丝钉"品牌名这类误伤。
7. **"其他"桶占比 ≥35% 会有 WARNING。** 分类结果里的 `uncategorized_samples` 是没命中任何类别的原文抽样，
   在脚本执行时的 stdout 里能看到，也存在 `classification.json` 的 `uncategorized_samples` 字段里——但**不再写进
   飞书文档正文**（用户 2026-08-06 批注要求删掉这一段，之前文档里有个「四点五、"其他"未归类抽样」段落，现在
   `generate_report.py` 已经不生成它了）。每期看一眼 stdout/json，反复出现的问法就该加进 `categories.md`。
8. **飞书文档更新用 block_insert_after 插入模式，只增不删，绝不 overwrite**，避免覆盖丢失历史内容。
9. 报告中的「情绪变化」和「选题建议」需 AI 基于数据分析后**人工撰写**，`generate_report.py` 生成的占位文本里已经
   写明了具体撰写要求（引用原文、点名环比数字、不能和上期选题重复），照着写而不是随便填两句。
10. **「六、建议直播选题」固定写 5 个方向，不是 3-5 个。** 用户 2026-08-06 批注明确要求 5 个，"3个太少"——
    `generate_report.py` 的占位文本已经改成"5 个"，写的时候照着数，不要图省事只写3个。
11. **写选题前查一遍真实播出记录，避免明显撞车。** 用户 2026-08-13 明确要求参考已经做过的直播。
    `lark-cli api GET /open-apis/drive/v1/files --params '{"folder_token":"IscSfJSjXl1nvIdActdcwwAKnDg","page_size":30}'`
    拉最新一页"每周直播大纲"文件夹（token 2026-08-13 才修正过，见 `report_format.md`），扫一眼"（已确认）"的
    标题，避开主题明显重复的。**只看标题级别，不用逐篇打开大纲正文比对。**
12. **改了这个 skill 的任何文件之后，记得 commit + push 到 GitHub（`fanlili321/yhlsd-live-topic-analysis`
    私有仓库，2026-08-13 起）。** 不用再手动 zip 备份到 Desktop——git 就是备份和版本历史。执行日常分析任务
    （跑第1-4步）不需要 push，只有**改了 skill 本身的代码/规则**才需要。commit message 简单说清楚改了什么、
    为什么改就行，不用太讲究格式。
