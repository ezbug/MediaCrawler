# POLYV 需求雷达

这是 MediaCrawler 的本地旁路分析层：MediaCrawler 负责低频抓取，雷达负责统一字段、去重、规则评分和 Markdown 报告。

所有页面操作只使用用户已登录的 Ego Lite 会话。需求信号默认保留 90 天，仍只处理公开/授权信息，并按仓库许可证进行本机非商业低频测试。

首轮配置位于 `local_tools/polyv_radar/pilot.toml`，运行数据位于仓库外的 `polyv-radar-data/`。

```bash
POLYV_TASKSPACE_ID=<current-taskspace> uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <current-taskspace>
```

浏览器会话必须由用户提供；TaskSpace 不存在、登录失效或页面受限时，任务会停止并记录状态，不会新建备用浏览器空间。

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
  --run-id <run-id> --lead-id <lead-id>

uv run python -m local_tools.polyv_radar daily \
  --config local_tools/polyv_radar/pilot.toml \
  --taskspace <current-taskspace>
```

历史 `pushed`、截图和 OCR 标记统一按 `legacy_unverified` 导入，未重新定位和重新找到发布文本前不会进入发送成功状态。真实发送必须同时显式传入 `--submit` 和用户当前 TaskSpace，私信始终只生成草稿。

最终交付文件位于数据目录的 `reports/`：

- `<run-id>-verified-leads.md`
- `<run-id>-verified-leads.jsonl`
- `<run-id>-locator-checks.json`

计入交付表的记录必须满足评分至少 4、企业场景及项目/选型/价格/交付证据成立、页面和原话可在 Ego Lite 中重新找到，并且同一用户或同一企业不重复。评论筛选窗口为 90 天；时间无法确认的评论不自动获得近期项目加分。
