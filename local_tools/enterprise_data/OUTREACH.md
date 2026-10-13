# 活动证据与邮件审核

默认公司池沿用当前邮件库的海尔、美的、东软、用友、金蝶、有赞、微盟。
变更名单只编辑 `outreach-targets.json`，不把竞品自动加入宣传发送池。

## 数据流

Ego Lite 搜索与公告读取 → 原始页面快照 → 同句公司/事件/日期抽取 →
未来60天事件去重 → 邮件填充 → 逐封审核 → Gmail 草稿/明确提交。

活动优先使用企业官网、交易所和公开披露渠道。搜索摘要只用于发现链接，不能作为
活动证据。东方财富的公告全文作为公开披露渠道保留；其他媒体不自动进入允许域。
跨句日期、PDF未渲染、缺年份、多日期歧义都保留采集快照，暂不生成活动记录。
零活动如实记录，禁止补造钩子。

## 命令

在当前 worktree 执行，以下 `OUTPUT` 指仓库外 `enterprise/outreach/activity-review`。

```bash
uv run python -m local_tools.enterprise_data.outreach \
  --config local_tools/enterprise_data/outreach-targets.json --output "$OUTPUT" collect --taskspace 9
uv run python -m local_tools.enterprise_data.outreach \
  --config local_tools/enterprise_data/outreach-targets.json --output "$OUTPUT" audit --emails emails.json
uv run python -m local_tools.enterprise_data.outreach \
  --config local_tools/enterprise_data/outreach-targets.json --output "$OUTPUT" generate --request request.json
uv run python -m local_tools.enterprise_data.outreach \
  --config local_tools/enterprise_data/outreach-targets.json --output "$OUTPUT" send --email email.json --taskspace 8
```

TaskSpace 数字仅为示例，运行前查询现有 Agent 空间，不接管用户空间。
最后一个命令默认只写草稿，只有添加 `--submit` 才点击发送。
发送入口当场重新审核并校验正文哈希、Gmail实填文本和唯一收件人。
当天以前的审核失效；来源快照超过一天则要求重新采集。
已开始的发送尝试不自动重试，异常后检查实际已发送邮件。
已拦截记录只能进入人工确认队列，代码没有 `force` 或跳过审核选项。
已拦截公司/收件人组合保持待人工确认状态，后来补到证据也不会自动放行；
只有收到用户明确确认后才可记入人工确认，之后仍须通过所有事实校验。
旧 `/tmp/gmail-send-*.mjs` 脚本已停用；后续统一调用此入口。

邮件输入字段：`company_id/company/event_id/event_name/event_date/business_line/to/recipient_role/subject/hook/body`。
`generate` 请求的正文必须有且只有一个 `{hook}`，事件字段由证据填入。
所有测试、审核内部语句与未填模板变量都禁止出现在最终正文。
收件职能按邮箱前缀和公司域名核对；无法确认的职能需要人工补证。
IR说明会只匹配IR邮箱，培训邮箱不能借用IR事件；分红和股东大会自动拦截。

产物：`source-captures.json`、`events.json`、`collection-status.json`、
`history/`、`audit-results.json`、`manual-confirmation-queue.json`、`send-preflight.json`。
这些都在仓库外。发送确认后追加原发送台账；配置 `obsidian_sync` 的 vault/email_probe/db
后自动重导出卡片。Gmail UI确认和最终送达分别记录；退信仍走现有可达性流程。
当前机器的同步配置已写入仓库外 `enterprise/outreach/outreach-runtime.json`，
真实提交时 `--config` 使用这个本地文件；缺少同步配置时发送入口直接停止。

## 海尔事实勘误

2026-10-08公告（临2026-061）全文显示半年报于2026-08-28发布，
半年度业绩说明会计划于2026-10-16 14:00–15:00以网络互动方式举行。
半年报发布日期不等于说明会日期。原发给培训邮箱的事故邮件因职能不匹配被拦截，
无需编造“说明会已开完”的理由。

## 日常任务

每天北京时间09:00进行活动采集和待发审核。任务只更新数据与人工队列，不发送。
采集失败保留错误与时间；当日缺证据不得使用旧审核放行。
自动任务由Codex应用管理，停用或调整时间在应用中进行。
