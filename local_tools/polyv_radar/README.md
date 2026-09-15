# POLYV 需求雷达

这是 MediaCrawler 的本地旁路分析层：MediaCrawler 负责低频抓取，雷达负责统一字段、去重、规则评分和 Markdown 报告。

采集后端可选 `native`、`ego` 或 `hybrid`。原生后端按平台批量关键词启动一次 MediaCrawler；混合后端仅在原生任务异常时回退 Ego。需求信号默认保留 90 天，仍只处理公开/授权信息，并按仓库许可证进行本机非商业低频测试。

首轮配置位于 `local_tools/polyv_radar/pilot.toml`，运行数据位于仓库外的 `polyv-radar-data/`。

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml
```

显式运行原生批量采集：

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml \
  --collector native \
  --platform dy
```

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
  --run-id <run-id>
```

如果任务被手动中断或单个关键词超过 `pilot.toml` 中的 `task_timeout_seconds`，先恢复已经写入的 JSONL，再执行分析：

```bash
uv run python -m local_tools.polyv_radar ingest \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id>
```

规则层只生成复核队列和回复草稿，不自动发表评论或联系用户。四个平台任务串行运行；平台登录失效、超时或非零退出会记录为部分失败，并保留已抓到的数据。

运行后端 A/B 基准（只生成对比文件，不参与评分）：

```bash
uv run python -m local_tools.polyv_radar benchmark \
  --config local_tools/polyv_radar/pilot.toml \
  --platform dy \
  --keyword "公司年会直播 平台报价" \
  --keyword "员工线上培训 平台推荐" \
  --keyword "医学学术会议 直播平台"
```

报告生成时会自动校验报告里的原文、主页和外部证据链接，并额外写出 `*-url-checks.json`。也可以只对已有批次重新生成带校验结果的报告：

```bash
uv run python -m local_tools.polyv_radar validate-urls \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id>
```

## 可核验潜客寻找

`locate` 和 `hunt` 的页面访问、评论展开、主页调查与链接校验全部通过 Ego Lite TaskSpace 8 完成。默认只读，不发表评论或发送私信；评论没有平台直链时，报告会同时保留内容 URL、作者、完整原话和父评论关系。

对已有批次执行评论定位和报告校验：

```bash
uv run python -m local_tools.polyv_radar locate \
  --config local_tools/polyv_radar/pilot.toml \
  --run-id <run-id> \
  --taskspace 8
```

执行最多两轮的候选寻找，不足目标时自动增加长尾业务事件查询；`--run-id` 会先复用旧批次，不重复抓取第一轮：

```bash
uv run python -m local_tools.polyv_radar hunt \
  --config local_tools/polyv_radar/pilot.toml \
  --collector ego \
  --taskspace 8 \
  --target-leads 20 \
  --max-candidates 80 \
  --max-batches 2
```

最终交付文件位于数据目录的 `reports/`：

- `<run-id>-verified-leads.md`
- `<run-id>-verified-leads.jsonl`
- `<run-id>-locator-checks.json`

计入交付表的记录必须满足评分至少 4、企业场景及项目/选型/价格/交付证据成立、页面和原话可在 Ego Lite 中重新找到，并且同一用户或同一企业不重复。评论筛选窗口为 90 天；时间无法确认的评论不自动获得近期项目加分。
