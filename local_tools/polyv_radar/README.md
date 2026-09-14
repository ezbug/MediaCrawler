# POLYV 需求雷达

这是 MediaCrawler 的本地旁路分析层：MediaCrawler 负责低频抓取，雷达负责统一字段、去重、规则评分和 Markdown 报告。

首轮配置位于 `local_tools/polyv_radar/pilot.toml`，运行数据位于仓库外的 `polyv-radar-data/`。

```bash
uv run python -m local_tools.polyv_radar collect \
  --config local_tools/polyv_radar/pilot.toml
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

规则层只生成复核队列和回复草稿，不自动发表评论或联系用户。四个平台任务串行运行；平台登录失效会记录为失败并继续处理其他平台。
