# 交接资料索引（handoff-sources.md）

> **本文件只列路径与用途，不写任何计数。** 活动性计数只留在活动交接文件
> `H/handoff/hermes-takeover-latest.md/.json`，避免两处数字漂移。

## 路径别名

| 别名 | 实际路径 |
|---|---|
| `W` | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit` |
| `D` | `/Users/sexpistole111/Documents/workplace/polyv-radar-data` |
| `S` | `/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply` |
| `H` | `/Users/sexpistole111/Documents/workplace/hermes-work` ← **Hermes 接管后全部产出** |
| Hermes | `/Users/sexpistole111/.hermes/hermes-agent` |
| Hermes 现行配置 | `/Users/sexpistole111/.hermes/config.yaml` |

> `H` 位于 Codex 交接会话所属 project 的根目录
> （project `workplace`，`rootPaths = ["/Users/sexpistole111/Documents/workplace"]`）。

## 1. 设计与代码（`W`）

目录：`W/local_tools/polyv_radar/`

- `README.md` — 设计与文件地图、快照验收方法、Grok 接收边界
- `GROK_HANDOFF.md` — Grok 协作边界；**明确禁止 Grok 回写** `manifest.json`、
  `lead-ledger.jsonl`、发送队列、`reply_history.jsonl` 或旧批次记录
- `pilot.toml` — 采集/审核限额等运行配置
- 采集 / 评分 / 调查 / 定位 / 复核 / 发送 / 报告模块：
  `runner.py` `pipeline.py` `scoring.py` `cleaning.py` `enrichment.py` `hunt.py`
  `locator.py` `review.py` `dispatch.py` `report.py` `html_dashboard.py` `dashboard.py`
  `storage.py` `handoff.py` `takeover.py` `cli.py`
- Ego 浏览器层：`ego_*.mjs` / `ego_*.py`（知乎、小红书、抖音、B站、评论定位、主页补全）
- 测试：`W/tests/test_polyv*.py`、`W/tests/auto_reply_safety.test.mjs`、
  `W/tests/search_relevance.test.mjs`

## 2. 规则与词库

**两份词库用途不同，分别保留，不得合并：**

| 文件 | 用途 | 版本 |
|---|---|---|
| `W/local_tools/polyv_radar/polyv_radar_keyword_taxonomy.json` | 完整查询池（搜索/意图/负向过滤/六大业务场景） | **2.0.0** |
| `S/references/taxonomy.json` | 回复侧判定（事件分层、意向信号、身份证据、硬负向、未确认能力） | 无 version 字段 |

其他规则：
- `S/SKILL.md` — 现行回复 Skill 的边界与默认工作流
- `S/references/workflow.md` — 完整字段、分层、停止条件
- `S/references/institutional_demand_funnel.md` — 机构公开需求分流规则
- `S/scripts/auto_reply.mjs` — **活动账本的唯一写入方**（外置，须记录版本哈希与可恢复副本）

## 3. 运行历史（`D`）

- `D/reply_history.jsonl` — 社媒发送账本（活动账本）
- `D/campaigns/<campaign_id>/` — 每批次产物（候选、派发队列、dry-run、send、summary、dashboard）
- `D/reports/all-sent-leads-dashboard.html` — 全项目累计大板
- `D/reports/reply_preview_*.png` — 发送前预览截图（**不等于发布后截图**）
- `D/workflow-runs/`、`D/locate*/`、`D/review/`、`D/raw/`、`D/dispatch/`、`D/enrichment/`
- `D/radar.sqlite3` — 关系型状态库

## 4. 机构需求与 Grok 同步文件（`D/grok-work/polyv-100/`）

- `demand-leads-20-ledger.json` — **机构账本**（bucket / sales_priority / 计数口径）
- `demand-leads-20-*.csv|html|md` — 机构账本派生视图
- `codex-takeover-latest.md/.json` — 上一轮 Codex 接管交付（格式模板）
- `grok-to-codex-latest.md` — Grok→Codex 同步校验
- `activity-ledger.jsonl` — Grok 侧**事件日志**（非机构账本）
- 保留全部 Grok 原始同步文件，**不得由 Hermes 覆盖**

## 5. 不可变历史

- `D/handoff/polyv-100/snapshots/29da967d1b1c36a096f7/` — 只读快照
  （`manifest.json` / `lead-ledger.jsonl` / `manifest.sha256`，权限 `-r--r--r--`）
- `/Users/sexpistole111/Documents/GOODS/polyv寻客爬虫` — Antigravity 原目录，**仅作历史来源**

## 6. 产品依据

- `/Users/sexpistole111/Downloads/保利威-新员工入职培训-202608-广州 - 实习生.pdf`

**使用能力声明时必须引用实际页面，不得把未确认能力写成事实。**
（`S/references/taxonomy.json` 中的 `unverified_capabilities` 列出未确认项。）
