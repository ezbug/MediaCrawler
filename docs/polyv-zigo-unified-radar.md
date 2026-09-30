# POLYV + ZigoAI 统一雷达

## 数据边界

- POLYV 数据库：`/Users/sexpistole111/Documents/workplace/polyv-radar-data/radar.sqlite3`
- ZigoAI 数据库：`/Users/sexpistole111/Documents/workplace/polyv-radar-data/zigoai/radar.sqlite3`
- ZigoAI 的 `sales_agent` 和 `geo` 使用独立产品域；原始 JSONL 仍保存在各自目录。
- 统一 API 只读两个数据库，展示层合并，不跨品牌写入评分、发送或回查状态。

## 资料关键词

从 ZigoAI 项目根目录生成版本化关键词注册表。每条记录包含产品域、分类、材料文件、页码、材料哈希和派生标记。

```sh
uv run python -m local_tools.polyv_radar zigo-keywords \
  --config local_tools/polyv_radar/zigo-sales.toml \
  --knowledge-root /Users/sexpistole111/Documents/GOODS/ZIgoAI \
  --output /Users/sexpistole111/Documents/workplace/polyv-radar-data/zigoai/keyword-registry.json \
  --persist
```

`material_excerpt` 表示关键词在对应产品域的资料页出现；`curated_search_term` 表示为搜索覆盖整理的词。后者不能被当作产品资料原文或能力承诺。

## ZigoAI 入库

采集和筛选结果仍由 ZigoAI 只读发现流程生成。需要重放已落盘 JSONL 时：

```sh
uv run python -m local_tools.polyv_radar zigo-ingest \
  --config local_tools/polyv_radar/zigo-sales.toml \
  --run-id 20260930-sales-r1b-xhs \
  --keyword-registry /Users/sexpistole111/Documents/workplace/polyv-radar-data/zigoai/keyword-registry.json
```

重复运行同一 `run_id` 是幂等的，不会新增内容、评论或入库事件。GEO 没有真实批次时保持为空，不用测试数据补齐。

## 本地大板

启动本地 API 后访问 `http://127.0.0.1:8080/`。雷达面板支持全部、POLYV、ZigoAI，以及 ZigoAI 产品域和批次筛选。ZigoAI 当前仅展示发现、筛选和证据状态，发送功能关闭。

统一只读接口：

- `GET /api/radar/unified/summary`
- `GET /api/radar/unified/runs`
- `GET /api/radar/unified/leads`
- `GET /api/radar/unified/revision`
- `WebSocket /api/ws/radar`

页面通过 WebSocket 接收数据库变更标识，并以 5 秒定时刷新作为断线补偿。API 不接受数据库路径参数。
