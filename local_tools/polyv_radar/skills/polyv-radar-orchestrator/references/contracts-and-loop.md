# 委派契约与 Goal Loop（contracts-and-loop.md）

## 1. Context 模板（传给子代理的片段）

```json
{
  "job_id": "…",
  "campaign_id": "…",
  "lane": "buyer_demand | provider_outreach | institutional_demand",
  "rules_version": "taxonomy 2.0.0 / prompt <hash>",
  "input_record_ids": ["…"],
  "evidence_files": [{"path": "…", "sha256": "…"}],
  "authorization_scope": {"campaign_id": "…", "platforms": ["…"], "budget": 0, "expires": "…"},
  "output_dir": "H/<campaign>/jobs/<job>/<attempt>/",
  "browser_lease": "none | collector | verifier",
  "patch_budget": 2
}
```

**只传相关片段**：不传全部会话、Cookie、整个数据库、其他 lane 的记录。

## 2. Goal 模板

> 处理**指定记录**，产出**指定证据或判断**；满足列出的**完成标准**；缺证据返回**阻塞**，
> **不扩大范围**。

限额：
- 采集：沿用 `W/local_tools/polyv_radar/pilot.toml` 配置限额
- **分析与复核：每批最多 2 条，输入 ≤ 12KB**

## 3. Return 模板

```json
{
  "job_id": "…",
  "status": "ok | partial | blocked",
  "artifact_path": "…",
  "sha256": "…",
  "counts": {},
  "findings": [],
  "failures": [],
  "next_requests": []
}
```

摘要 ≤ 约 1200 tokens。产物写入 `H/<campaign>/jobs/<job>/<attempt>/`，
**只有主代理合并**。

## 4. Goal Loop

```
读取基线与唯一写入权 → 明确类型、目标、授权及预算 → 建立断点
委派独立任务；保存 delegate_task 返回的任务 ID，等待终态结果
核对结构、哈希、引用、身份/时间归属和类型；主代理裁决分歧
缺证据     → 定向补采
格式/判断错误 → 原任务修补，合计最多两次
登录拦截或提交结果不明 → 暂停对应分支；其余任务继续，逐条保存
通过 → 既有模型复核 → 定位 → 草稿 → Dry-Run → 主代理验收
存在本活动发送授权才提交；提交后核验 → 逐条落账 → 更新同源大板
达到目标或两轮采集用尽即交付实际数量、缺口、阻塞及恢复点
```

**异步语义（关键）：** Hermes 的 `delegate_task` 是**异步委派**；使用
`goal / context / role="leaf" / output_schema`，**不把"启动成功"当任务完成**——必须等待终态结果。
内置格式修补计入修补预算。**进程重启后从项目产物恢复，不直接重跑可能已经提交的任务。**

## 5. 授权与预算

- 自动公开回复能力必须保留；在**明确活动授权、目标范围和数量预算内**自动运行，
  **无需逐条重复索取同一授权**。
- **历史授权不得扩展到新的无限量活动。** 每个新活动需要新的 `authorization_scope`。
- 发送前的四项硬检查：**活动授权 / 去重 / 目标关系 / 最终草稿**。
- 提交后的三项核验：**我方账号 / 完整文本 / 目标关系**。
- **点击与核验分别落账**；结果不明**只回查，不重发**。

## 6. 唯写入权（唯一写入方）

| 资产 | 唯一写入方 |
|---|---|
| `D/reply_history.jsonl`（活动账本） | `S/scripts/auto_reply.mjs`（经主代理 `dispatch` 入口调用） |
| 机构账本 `demand-leads-20-ledger.json` | 主代理（接管后） |
| `D/handoff/**/snapshots/**` | **无（只读不可变）** |

接管纪律：**Codex、Grok 和子代理均不得并行修改活动账本。** 子代理只写自己
`jobs/<job>/<attempt>/` 下的产物。

## 7. 必须优先修复的缺陷（对应 SKILL.md）

| # | 缺陷 | 证据 | 修复方向 |
|---|---|---|---|
| 1 | 发送点击与核验状态未分离 | `auto_reply.mjs:595` `submitted = verified;` | 分别落账 `clicked` / `verified`；`clicked` 记录点击动作本身 |
| 2 | 每条操作未及时落账 | 账号本行缺失的异常候选（见交付报告） | 每次操作立即 append，失败也落一条 |
| 3 | 发送核验缺账号与目标关系 | 回查只比对文本 | 补齐"我方账号 + 目标关系"校验 |
| 4 | Dry-Run 无结构化证据且不清理草稿 | 需补 | 结构化证据 + 退出时清理编辑器草稿 |
| 5 | 去重依赖文案 | 实测同一目标被二次触达（不同草稿） | 去重键改为**目标身份**，不含草稿文本 |
| 6 | 累计大板计数口径不一致 | 顶部/表内两套去重键 | **所有计数从同一数据视图生成** |
| 7 | 截图证据随窗口状态丢失 | 窗口最小化时 `Page.captureScreenshot` 超时（15 003 ms vs 恢复后 47 ms） | 截图前调用 `ensureWindowRestored()`；落账 `window_restored` / `evidence_source` |

补充：外置的 `S/scripts/auto_reply.mjs` 必须记录**版本哈希**并保留**可恢复副本**。

## 8. 验收测试（在现有测试之外新增）

保留现有 **137 项 Python + 30 项 Node** 全绿，新增：

1. 文案变化 → 去重仍生效（同目标不同草稿不重复触达）
2. 不同评论目标 → 不被误合并（同一页两条不同原话算两个目标）
3. 编辑器文本 → 不被误判为已发布
4. 点击后超时 → **不重发**
5. Worker 重复结果 → 幂等
6. 三类型隔离 → 不互相垫数
7. 大板计数一致性 → 顶部与表内同源

**首轮真实页面样本最多 5 条，仅定位与 Dry-Run，发送数增量必须为 0。**

## 9. 交付标准

输出 `H/handoff/hermes-takeover-latest.md` + `.json`，记录：

- Git SHA（含工作树是否干净）
- 来源清单 + SHA-256
- 实际计数（修正前后对照）
- 证据审计（含异常逐条回查结论）
- 测试结果（实际执行输出）
- 当前阻塞
- **唯一写入方**
- 可恢复的下一步

**永久 Skill 不固化临时数量**（数字只留在活动交接文件）。
代码及文档验证后**分阶段提交**；数据库、截图、日志、Cookie 及 TaskSpace 凭据**留在仓库外**。
