# yhlsd 直播选题分析 — 完整执行包

## 这是什么

银行螺丝钉（yhlsd.com）直播选题分析工具。从客户互动中枢拉取微信公众号、知识星球、微博、企业微信近4天客户留言（**固定4天，用户2026-08-13明确要求的规则，不要改成7天**），按13类分类清洗分析高频问题，生成选题报告写入飞书文档，并推送摘要到飞书聊天。

## 另一个 AI 执行清单

收到这个包后，按以下步骤操作：

### 0. 环境准备
```bash
pip install requests   # 唯一依赖
```

### 1. 拉取留言
```bash
cd /tmp
python3 scripts/fetch_messages.py --days 4 --output /tmp/yhlsd_automation/messages_raw.json
```
- 通过 Hub API（Bearer token）一次请求拉取全量，无需翻页
- `--days 4` 是固定规则，不要改，见上面"这是什么"里的说明
- 验证：4天窗口企业微信大约 600-750 条，明显偏低说明 token 失效

### 2. 清洗与分类
```bash
# 先保存上期快照（如果存在）
cp /tmp/yhlsd_automation/classification.json /tmp/yhlsd_automation/classification_prev.json 2>/dev/null

# 运行分类
python3 scripts/classify_messages.py --input /tmp/yhlsd_automation/messages_raw.json --output /tmp/yhlsd_automation/classification.json
```
- 自动剔除主理人（钉大/螺丝钉）回复、营销推送、无意义短文本
- 按13类关键词分类（可重叠）

### 3. 生成报告 + 更新飞书文档
```bash
# 生成XML骨架（含环比对比、数据质量提示）
python3 scripts/generate_report.py \
  --input /tmp/yhlsd_automation/classification.json \
  --previous /tmp/yhlsd_automation/classification_prev.json \
  --output /tmp/yhlsd_automation/report.xml

# 读取report.xml，手动补充第5节（用户情绪）和第6节（选题建议）
# ⚠️ 撰写要求已经写在 report.xml 生成的占位文本里：必须引用原文、必须点名环比数字、
#    不能重复上期选题结论。第6节固定写5个选题方向（用户2026-08-06批注要求，不是3-5个，不要减少）。
#    照着占位文本的要求写，不要随便填两句。
#
# ⚠️ "其他"未归类抽样不再写进文档正文（用户2026-08-06批注要求删除这一段）。
#    classify_messages.py 仍会算，在 stdout WARNING 和 classification.json 的
#    uncategorized_samples 字段里能看到，只是不进 Feishu 文档了。
```

**⚠️ 只增不删，绝不用 `overwrite` 覆盖飞书文档！** 之前的版本用 `overwrite` 整篇替换，有覆盖丢失历史内容
的风险，已经改成 `block_insert_after` 只在 title 块后插入：

```bash
# 1. 拉取文档，带 block ID（2026-08-06 实测：lark-cli 1.0.84 返回的是一整段 content 字符串，
#    每个标签内联 id="..." 属性，不是 blocks 数组——之前这里写的 doc['data']['document']['blocks']
#    是错的，会直接 KeyError）
lark-cli docs +fetch --doc KsInd8S1ko6jQgxlypncNcqanPe --detail with-ids > /tmp/doc_with_ids.json

# 2. 从 content 字符串开头解析出 title 的 id（<title id="...">），拼好待插入内容存成文件
python3 -c "
import json, re
with open('/tmp/doc_with_ids.json') as f:
    content = json.load(f)['data']['document']['content']
title_block_id = re.match(r'<title id=\"([^\"]+)\"', content).group(1)
with open('/tmp/yhlsd_automation/report.xml') as f:
    report = f.read()
combined = '<hr/><hr/>' + report
with open('/tmp/yhlsd_automation/insert_content.xml', 'w') as f:
    f.write(combined)
print('title_block_id:', title_block_id)
"

# 3. 插入。--content 只接受相对路径的 @file 或 - 读 stdin，不接受绝对路径 @file，
#    所以用 cat | ... --content - 传内容，不要把整段 XML 塞进 argv
cat /tmp/yhlsd_automation/insert_content.xml | lark-cli docs +update --doc KsInd8S1ko6jQgxlypncNcqanPe \
  --command block_insert_after --block-id <title_block_id> --content -
```

### 4. 发送飞书通知
只发一句"执行完毕 + 链接"，**不要发长摘要**（用户 2026-08-06 明确要求，之前带 TOP3/选题建议的长版本已废弃）：
```bash
lark-cli im +messages-send --chat-id oc_94c21bc74eb7413a61c4647ca15a78ea --text "【AI直播选题分析】{日期范围} 已更新：https://epndqwwg0a.feishu.cn/docx/KsInd8S1ko6jQgxlypncNcqanPe"
```

## 关键配置

| 配置项 | 值 |
|--------|-----|
| Hub API URL | http://qa.yhlsd.com/hub/api/messages |
| 鉴权方式 | Bearer token（已内置在 fetch_messages.py DEFAULT_TOKEN） |
| Token 获取 | 飞书扫码 https://qa.yhlsd.com/hub/ → AI接口token |
| 飞书文档 token | KsInd8S1ko6jQgxlypncNcqanPe |
| 飞书文档链接 | https://epndqwwg0a.feishu.cn/docx/KsInd8S1ko6jQgxlypncNcqanPe |
| 推送 chat（范丽丽的飞书CLI） | oc_94c21bc74eb7413a61c4647ca15a78ea |
| 数据窗口 | 最近4天（--days 4，固定规则，2026-08-13起，不要改） |
| 分类体系 | 13类（唯一数据源在 references/categories.md，classify_messages.py 动态解析） |

## 定时任务

每周二、周四 14:00 北京时间自动执行（通过 WorkBuddy automation 管理）。

## 文件结构
```
├── RUNME.md              ← 这个文件
├── SKILL.md              ← 完整技能说明
├── scripts/
│   ├── fetch_messages.py     ← Hub API 拉取（Bearer token，一次请求全量）
│   ├── classify_messages.py  ← 清洗 + 13类关键词分类
│   └── generate_report.py    ← 生成飞书文档 XML（支持 --previous 环比对比）
└── references/
    ├── categories.md         ← 13类完整关键词与清洗规则
    └── report_format.md      ← 文档结构规范 + 消息格式
```
