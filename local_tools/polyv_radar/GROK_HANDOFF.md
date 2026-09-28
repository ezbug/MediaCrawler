# POLYV 雷达交接给 Grok Bot

## 分工与账本边界

- Codex 负责本机代码、测试、Git 和只读交接快照；交付快照后停止写活动账本。
- Grok Bot 负责验收快照、组织多 Bot 协作并推进 100 条任务。
- 快照文件只读、不可覆盖。Grok 不得回写 `manifest.json`、`lead-ledger.jsonl`、发送队列、`reply_history.jsonl` 或旧批次记录；运行期间由 Grok 协调者维护独立工作账本，子 Bot 只返回各自结果，不并发写总账。
- Grok 的本地应用位于 `/Applications/Grok Bot.app`，本机进程报告版本 `0.58.0`。项目文件权限、模型/API 状态和多 Bot 能力尚未验证；首次接手应通过 Grok 支持的界面检查，不能从应用进程存在推断权限可用。
- 机构公开需求与社媒公开回复是独立漏斗。Grok 的 `grok-to-codex-latest.{json,md}` 是活动交接输入；Codex 使用 `takeover-sync` 重算计数并生成 `codex-takeover-latest.{json,md}`，不覆盖 Grok 原始账本或不可变快照。
- 当前机构批次交付目标为可核验需求记录，不等同于开放商机；机构记录不得补入社媒100条回复计数。

## 本机文件地图

项目工作树：

```text
/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit
```

主要文件：

下表中首个路径为绝对路径；同一单元格后续文件名均与它位于同一目录 `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/`。

| 用途 | 路径 |
|---|---|
| 项目说明 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/README.md` |
| 运行配置 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/pilot.toml` |
| Antigravity v2.0.0 完整词库快照 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/polyv_radar_keyword_taxonomy.json` |
| 内容采集与调度 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/runner.py`、`adapters.py`、`ego_platform_batch.mjs`、`ego_dy_crawler.mjs`、`ego_xhs_crawler.mjs`、`ego_bili_crawler.mjs`、`ego_zhihu_crawler.mjs` |
| 初筛与评分 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/qna_batch.py`、`scoring.py`、`pipeline.py`、`review.py` |
| 主页与公开背景调查 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/enrichment.py`、`ego_profile_enricher.mjs`、`ego_web_search.mjs` |
| 评论定位与链接验证 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/locator.py`、`ego_comment_locator.mjs`、`ego_url_validator.mjs`、`url_validation.py` |
| 发送队列与记录 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/dispatch.py`、`approval.py`、`daily.py` |
| HTML 大板 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/html_dashboard.py`、`dashboard.py` |
| CLI 入口 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/__main__.py`、`cli.py` |
| 交接导出器 | `/Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit/local_tools/polyv_radar/handoff.py` |
| 数据库 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/radar.sqlite3` |
| 回复历史 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/reply_history.jsonl` |
| 当前 100 条候选池 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/locators/20260923-leads100-input.json`、`/Users/sexpistole111/Documents/workplace/polyv-radar-data/locators/20260923-leads100-output.json` |
| 严格发送队列及结果 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/dispatch/20260923-leads100-strict.jsonl`、`/Users/sexpistole111/Documents/workplace/polyv-radar-data/dispatch/dispatch-20260923-leads100-strict-live.jsonl` |
| 当前日报 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/reports/20260923-leads100-dispatch-summary.md` |
| 快照目录 | `/Users/sexpistole111/Documents/workplace/polyv-radar-data/handoff/polyv-100/snapshots/<snapshot_id>/` |

完整运行规则和发送脚本在仓库外 Skill：

```text
/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/SKILL.md
/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/references/workflow.md
/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/references/taxonomy.json
/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply
/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs
```

浏览器依赖本机 Ego Lite/jev-ego。TaskSpace 编号、登录 Cookie、`.env`、认证文件及代理凭据不在仓库或交接快照内。Grok 需验证自己受支持的项目/浏览器连接；不得复制 Codex 或 Ego 的登录态文件。

## 当前基线生成

先做不落盘预览，再正式导出：

```bash
cd /Users/sexpistole111/Documents/workplace/MediaCrawler/.worktrees/polyv-antigravity-inherit
uv run python -m local_tools.polyv_radar handoff-export \
  --config local_tools/polyv_radar/pilot.toml \
  --campaign polyv-100 --dry-run

uv run python -m local_tools.polyv_radar handoff-export \
  --config local_tools/polyv_radar/pilot.toml \
  --campaign polyv-100
```

如果同一 campaign 下严格队列不唯一，命令会停止并要求显式给出 `--queue`。质量复核文件可通过 `--quality-review` 指定；缺省位置是：

```text
/Users/sexpistole111/Documents/workplace/polyv-radar-data/review/polyv-100-quality-review.jsonl
```

导出器只读取源数据。清单包含 Git SHA、源文件 SHA-256、候选池、严格队列、发送结果、回复历史逐行哈希、数据库源哈希、截图文件哈希、稳定去重键及逐条质量/定位/发送状态。导出链接会移除临时查询令牌，保留页面路径和评论锚点。截图不复制，账本只记录原路径和哈希。

发送完成数要求发送结果与回复历史对同一平台、URL、作者和回复文本都报告 `submitted=true`、`verified=true`。这表示本机自动化记录了发布后文本回查；发送前截图只证明目标和草稿预览。合格需求数只认质量复核文件明确标为合格的记录，不能用“已发送”替代“合格潜客”。

截至 2026-09-23 本地证据：定位池 100 条，定位成功 29 条、未命中 71 条；严格发送队列 19 条，发送结果与回复历史双重匹配 10 条，暂停 9 条。其中 4 条已发送和 6 条暂停可回连定位池；另外 6 条已发送和 3 条暂停仅出现在严格队列/补充来源中。逐条质量审查了 10 条已发送记录：0 条可确认为合格，1 条因知乎答主正文缺失而待复核，8 条没有显示 POLYV 数字化交付/平台采购需求，1 条属于原帖服务商发布者。定位池中 96 条未完成质量判定（含 6 条暂停记录和 90 条未进入严格队列的候选）；9 条队列外补入记录中有 3 条暂停未做质量判定。故 100 条合格目标的真实剩余差额仍待审完候选后计算，不按 10 条发送数推算。

## Grok 接收验收

1. 按快照 `manifest.json` 中的 `git_revision` 打开对应分支，验证 `manifest.sha256`、账本 SHA-256 和 `sources` 中的文件哈希。
2. 区分 `source_scope`（定位池/发送队列外补入）、`quality.status`（已复核/未审/不成立）和 `locator.status`（已定位/未命中）。
3. 把既有已回查发送和暂停记录视为历史事实，不重发；按 `dedupe_key` 识别重复工作项。
4. 在 Grok 自己的工作区创建活动账本。子 Bot 只提交各自结果，由唯一协调者串行合并，不并发修改总账。
5. 先复核未审候选和证据缺口；分别记录需求质量、原文定位、身份依据、草稿审核和发送结果。没有证据的项目不升级为合格线索。
6. 验证 Grok 的本机项目权限、支持的浏览器连接和多 Bot 能力后，再分派候选审查、证据补齐及回复草拟；未经验证的连接不视为已部署。

建议的只读并行分工：

- Bot A：核对需求证据，返回 candidate ID、原文、结论和理由。
- Bot B：核对评论定位、父子关系和链接状态，只返回差异。
- Bot C：检查身份依据、内容来源噪声和重复项；缺少 author ID 时不按昵称合并。
- Grok 协调者：解决分歧并串行更新自己的工作账本，决定下一阶段动作。

## Grok 接收 Prompt

```text
我把 POLYV 雷达的 100 条候选任务交给你接手。先验收 Codex 提供的不可变快照，不要覆盖它，也不要把“发送成功”当成“潜客合格”。

先验证 manifest 中的 Git 基线和源哈希，再分别检查候选池、已定位记录、未命中记录，以及严格队列中的发送成功和暂停状态。Codex 快照是只读审计基线；后续过程写入 Grok 自己的活动账本，不改历史发送记录。

请先检查 Grok 当前可用的本机项目权限、浏览器连接和多 Bot 能力。不要复制 Codex/Ego 的 Cookie、TaskSpace 或认证文件。多个 Bot 只做独立审查，由你作为唯一协调者串行合并。

逐条输出 candidate ID、内容/评论链接、完整原话、发布时间、定位状态、身份依据、去重键、质量结论和理由。缺少 POLYV 相关数字化视频/培训/活动交付需求、项目或采购意图证据的，标为待审或不成立，不为凑数升级。严格遵守仓库外的 polyv-lead-auto-reply/SKILL.md；失败项记录原因，不自动重复外联。

每轮交付：读取的快照 SHA、处理的 candidate ID、可核验证据、未解决原因、Grok 工作账本位置和下一轮队列。不要让多个 Bot 同时写一个账本。
```
