# POLYV 需求雷达

这是 MediaCrawler 的本地旁路分析层：MediaCrawler 负责低频抓取，雷达负责统一字段、去重、规则评分和 Markdown 报告。

首轮配置位于 `local_tools/polyv_radar/pilot.toml`，运行数据位于仓库外的 `polyv-radar-data/`。

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml
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
