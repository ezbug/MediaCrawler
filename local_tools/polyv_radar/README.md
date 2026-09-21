# POLYV 需求雷达

这是 MediaCrawler 的本地旁路分析层：MediaCrawler 负责低频抓取，雷达负责统一字段、去重、规则评分和 Markdown 报告。

所有页面操作只使用用户已登录的 Ego Lite 会话。需求信号默认保留 90 天，仍只处理公开/授权信息，并按仓库许可证进行本机非商业低频测试。

首轮配置位于 `local_tools/polyv_radar/pilot.toml`，运行数据位于仓库外的 `polyv-radar-data/`。

关键词同步：`polyv_radar_keyword_taxonomy.json` 是从 Antigravity
`polyv_radar_keyword_taxonomy.json` 原样保存的 v2.0.0 快照。配置会自动加载
Tier 1 核心场景和 Tier 2 验证场景，包含公司年会、员工大会、经销商大会、
合作伙伴大会、新品发布会、行业峰会、医学会议、招商会、订货会等企业活动词，
以及六类业务场景、岗位画像、采购信号和负向词。第二轮 `hunt` 会加入 Tier 3
实验查询和每个平台的第一人称长尾词。查询中的 `+` 只在提交平台搜索时规范为空格，
原始词库快照不被改写。

```bash
POLYV_TASKSPACE_ID=<current-taskspace> uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <current-taskspace>
```

浏览器会话必须由用户提供；TaskSpace 不存在、登录失效或页面受限时，任务会停止并记录状态，不会新建备用浏览器空间。

采集按平台批处理：每个平台只启动一次 Ego Lite Node 进程，复用同一个 TaskSpace 的 `p1` 页面顺序处理该平台关键词。每个关键词前后保存页面 Snapshot，运行记录和可复用流程候选写入：

```text
polyv-radar-data/workflow-runs/<run-id>/workflow-run.json
polyv-radar-data/workflow-runs/<run-id>/workflow-candidate.json
polyv-radar-data/workflow-runs/<run-id>/snapshots/
```

`workflow-candidate.json` 只代表待人工审查的流程候选，不会自动修改 Skill 或执行外联。批量 DOM、Shadow DOM 和评论树操作仍在同一 TaskSpace 内通过 `ego-browser` 的 `page.evaluate()` 完成。

只测试一个平台和关键词时，可以覆盖配置文件中的范围和数量：

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --platform dy \
  --keyword "员工培训" \
  --max-contents 5 \
  --max-comments 10 \
  --task-timeout-seconds 180
```

指定完整词库层级运行时，可以显式加入实验层：

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --platform xhs \
  --taxonomy-tier tier1_primary \
  --taxonomy-tier tier2_verify_demand \
  --taxonomy-tier tier3_experimental \
  --taskspace <current-taskspace>
```

传入 `--keyword` 的命令仍然是聚焦测试，默认暂时关闭词库扩展；需要在自定义关键词
上叠加词库时，同时传入 `--taxonomy-tier`。

采集完成后，使用输出中的 `run_id` 分析和生成报告：

```bash
uv run python -m local_tools.polyv_radar analyze \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id>

uv run python -m local_tools.polyv_radar report \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --taskspace <current-taskspace>
```

模型复核采用可续跑的小批模式：每批最多 2 条候选，默认使用
`gpt-5.6-luna + low`，批次超时后只对受影响记录单条重试一次；连续两次失败会熔断，
剩余记录进入 `model_pending_timeout` 或 `model_pending_invalid` 人工复核队列。每条结果
立即落库，缓存键包含候选、证据哈希和复核版本，重复运行不会覆盖已完成的其他候选。
模型通过、模型待审和模型拒绝在报告中分开统计；待审记录即使规则分数达标，也只能生成
明确标注“模型复核未完成”的人工草稿，不能直接进入自动发送队列。

模型调用和噪声分类可从报告漏斗查看。报告会区分 `buyer_request`、`provider_content`、
`guide_content`、`general_discussion` 和 `irrelevant`；服务商或教程内容仍可作为评论容器，
但发布者不会直接成为潜客。标题只提供业务场景，评论自身必须提供项目、选型、价格或交付证据。

如果任务被手动中断或单个关键词超过 `pilot.toml` 中的 `task_timeout_seconds`，先恢复已经写入的 JSONL，再执行分析：

```bash
uv run python -m local_tools.polyv_radar ingest \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id>
```

规则层可生成回复队列。默认 `dispatch` 只执行 Dry-Run；传入 `--submit` 后，会通过指定的 Ego Lite TaskSpace 自动逐条发布公开回复。每条均由发送脚本执行目标作者匹配、截图、去重、30 秒冷却、每日上限和发布后原文复核；失败不会自动重试或改发到顶层评论框。四个平台任务串行运行；平台登录失效、超时或非零退出会记录为部分失败，并保留已抓到的数据。

生成队列并自动发送公开回复：

```bash
uv run python -m local_tools.polyv_radar prepare-dispatch \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> --selection model

uv run python -m local_tools.polyv_radar dispatch \
  --config local_tools/polyv_radar/pilot.toml \
  --queue /Users/sexpistole111/Documents/workplace/polyv-radar-data/dispatch/<run-id>-model.jsonl \
  --taskspace <current-taskspace> --submit
```

`--selection manual` 只包含人工确认高价值记录；`--selection model` 包含模型复核通过且评论定位已验证的记录。当前自动发送范围仅为公开评论回复；私信开场和资料建议继续写入报告，供后续流程使用。

## 人工待选线索

正式评分门槛以下、但可能有学习价值的记录会单独保存，不会进入公开回复队列：

```bash
uv run python -m local_tools.polyv_radar manual-candidates \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --max-candidates 50
```

输出位置：

- `polyv-radar-data/review/<run-id>-manual-candidates.jsonl`
- `polyv-radar-data/reports/<run-id>-manual-candidates.md`

时间层分为 `current`（90天内）、`historical`（90天至730天）、`stale`（超过730天）和 `unknown`。历史记录只生成“确认现在是否仍有需求”的复活草稿；账号名只作来源角色提示，不能单独证明企业身份。服务商帖子可作为评论容器，但服务商评论者会从潜客待选池排除。

原生和混合后端基准已停用，避免产生不在 Ego Lite 中的页面操作。

报告生成时会自动校验报告里的原文、主页和外部证据链接，并额外写出 `*-url-checks.json`。也可以只对已有批次重新生成带校验结果的报告：

```bash
uv run python -m local_tools.polyv_radar validate-urls \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --taskspace <current-taskspace>
```

## 可核验潜客寻找

`locate` 和 `hunt` 的页面访问、评论展开、主页调查与链接校验全部通过用户显式提供的 Ego Lite TaskSpace 完成，不固定会话编号。默认只读，不发表评论或发送私信；评论没有平台直链时，报告会同时保留内容 URL、作者、完整原话和父评论关系。

对历史自动回复批次，可使用 `clean` 生成逐条发送证据账本。它只把当前回复历史中同时满足 live、submitted、verified 且截图存在的记录标为已验证发送；旧 `pushed`、旧截图和旧日志会单独保留为未验证证据。

```bash
uv run python -m local_tools.polyv_radar clean \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --reply-evidence <reply-evidence.json>
```

对已有批次执行评论定位和报告校验：

```bash
uv run python -m local_tools.polyv_radar locate \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --taskspace <current-taskspace>
```

执行最多两轮的候选寻找，不足目标时自动增加长尾业务事件查询；`--run-id` 会先复用旧批次，不重复抓取第一轮：

```bash
uv run python -m local_tools.polyv_radar hunt \
  --config local_tools/polyv_radar/pilot.toml \
  --collector ego \
  --taskspace <current-taskspace> \
  --target-leads 20 \
  --max-candidates 80 \
  --max-batches 2
```

历史接管与每日任务：

```bash
uv run python -m local_tools.polyv_radar import-antigravity \
  --config local_tools/polyv_radar/pilot.toml \
  --source "/Users/sexpistole111/Documents/GOODS/polyv寻客爬虫" \
  --session-id fef7c447-4c3d-4177-b1a5-10a55d3307da

uv run python -m local_tools.polyv_radar approve \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> --lead-id <lead-id> \
  --taskspace <current-taskspace>

uv run python -m local_tools.polyv_radar daily \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <current-taskspace>
```

审批会再次通过同一 Ego Lite TaskSpace 验证内容页面；普通 HTTP `403` 不等同于页面失效。作者为平台泛化占位名、内容超过 90 天、或攻略/选型文章缺少第一人称项目证据时，不会进入发送队列。真实发送必须同时显式传入 `--submit` 和用户当前 TaskSpace，私信始终只生成草稿。

最终交付文件位于数据目录的 `reports/`：

- `<run-id>-verified-leads.md`
- `<run-id>-verified-leads.jsonl`
- `<run-id>-locator-checks.json`

计入交付表的记录必须满足评分至少 4、企业场景及项目/选型/价格/交付证据成立、页面和原话可在 Ego Lite 中重新找到，并且同一用户或同一企业不重复。评论筛选窗口为 90 天；时间无法确认的评论不自动获得近期项目加分。
