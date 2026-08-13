# yhlsd 直播选题分析

银行螺丝钉（yhlsd.com）直播选题分析工具。从客户互动中枢拉取微信公众号、知识星球、微博、企业微信的近期客户留言，按13类分类体系清洗分析高频问题，生成选题报告写入飞书文档，并推送通知。用于直播前的高频问题分析和选题规划。

## 快速开始

```bash
git clone https://github.com/fanlili321/yhlsd-live-topic-analysis.git
cd yhlsd-live-topic-analysis
git pull --ff-only   # 每次执行前先拉最新代码，确保规则是最新的
pip install requests   # 唯一依赖
```

完整执行步骤见 [`SKILL.md`](SKILL.md)（权威版本，本 README 只是导览）。

## 工作流程

1. **拉取留言** — `scripts/fetch_messages.py`，通过 Hub API 一次请求拉取全量留言
2. **清洗分类** — `scripts/classify_messages.py`，剔除噪音后按13类关键词分类（关键词来自 `references/categories.md`）
3. **生成报告并写入飞书** — `scripts/generate_report.py` 生成骨架，人工/AI 补充定性分析，用 `block_insert_after` 插入文档（**绝不用 `overwrite`**，避免覆盖历史内容）
4. **发送通知** — 一句话通知，不发长摘要

## 几条硬性规则（都是踩过坑之后定下来的，别改）

- **数据窗口固定4天**（`--days 4`），周二、周四各跑一次，两次窗口本来就会重叠，这是接受的代价，不要改成动态计算
- **飞书文档只增不删**，用 `block_insert_after` 插到 title 块后面
- **标题不带"期"字**，只保留日期，如 `2026-08-13（覆盖 2026-08-09 ~ 2026-08-13）`
- **建议选题固定5个**，是并列独立的候选项供老板挑选，不写"选题串联逻辑"这种暗示串成系列的文字
- **写选题前查一遍"每周直播大纲"文件夹**（`IscSfJSjXl1nvIdActdcwwAKnDg`）里"（已确认）"的历史标题，避免和已经播过的话题明显撞车——标题级别查重就够
- **不生成"其他未归类抽样"段落**、**不生成"本期环比信号"排行榜式小节**——这两个都写进过文档又被要求删掉过，别加回去
- **通知只发一句话**：`【AI直播选题分析】{日期范围} 已更新：<文档链接>`，chat_id 是范丽丽本人和"范丽丽的飞书CLI"这个 bot 的 1v1 私聊，不是群
- **关键词只改 `references/categories.md` 一处**，`classify_messages.py` 运行时动态解析这个文件，不再自己维护第二份关键词字典

完整规则、每条规则的来龙去脉、历史踩坑记录见 [`SKILL.md`](SKILL.md) 和 [`MEMORY.md`](MEMORY.md)。

## 定时任务

每周二、周四 14:00（北京时间）自动执行，由 Claude Code 本地定时任务管理（不是云端，因为需要本机的
`lark-cli` 登录凭据和内网 API 访问）。执行前会先 `git pull` 同步最新代码。

## 文件结构

```
├── SKILL.md                    ← 完整技能说明，权威版本
├── RUNME.md                    ← 独立执行清单（给另一个 AI/协作者用）
├── MEMORY.md                   ← 项目记忆：历史改动、踩过的坑、为什么这么设计
├── USER_MEMORY.md              ← 用户偏好（文件存放位置等）
├── scripts/
│   ├── fetch_messages.py       ← Hub API 拉取，含数据量异常检测
│   ├── classify_messages.py    ← 清洗 + 13类关键词分类
│   └── generate_report.py      ← 生成飞书文档 XML
└── references/
    ├── categories.md           ← 13类关键词与清洗规则的唯一数据源
    └── report_format.md        ← 文档结构规范 + 消息格式
```

## 关键配置

| 配置项 | 值 |
|--------|-----|
| Hub API | `http://qa.yhlsd.com/hub/api/messages`，Bearer token 鉴权（token 会过期，需飞书扫码 https://qa.yhlsd.com/hub/ 重新获取） |
| 飞书文档 | `KsInd8S1ko6jQgxlypncNcqanPe` — https://epndqwwg0a.feishu.cn/docx/KsInd8S1ko6jQgxlypncNcqanPe |
| 推送 chat | `oc_94c21bc74eb7413a61c4647ca15a78ea`（范丽丽本人和飞书CLI bot 的私聊） |
| 直播大纲文件夹（查重用） | `IscSfJSjXl1nvIdActdcwwAKnDg` |

## 维护说明

- 改动这个仓库任何文件后记得 `git add -A && git commit && git push`——这就是备份，不用再手动 zip
- 这是 **private** 仓库，`fetch_messages.py` 里有一个真实的 Hub API token，不要把仓库改成 public
- 每次自动执行前会先 `git pull`，网页上改的内容下次运行自动生效
