# 企业数据归纳系统（第一版）

按《企业数据归纳系统设计》实现的 P0 数据层：企业主数据、年报财务年度数据、招聘职位快照、
招聘指标与数据证据，全部落在 SQLite，附带增长率/口径可比性/规模分层/招聘活动指数计算。

## 快速开始

```bash
DB=/Users/sexpistole111/Documents/workplace/polyv-radar-data/enterprise/enterprise.sqlite3

# 1. 建库（幂等）
uv run python -m local_tools.enterprise_data --db $DB init

# 2. 导入企业主数据（JSON 对象；可带 company_id，没有则自动生成）
uv run python -m local_tools.enterprise_data --db $DB import-company --json company.json

# 3. 导入年报财务（同一 company_id + 财年 + 口径 + 报告版本唯一，重复导入即更新）
uv run python -m local_tools.enterprise_data --db $DB import-financial --json fy2025.json

# 4. 导入职位快照（按 platform + platform_job_id 去重更新）
uv run python -m local_tools.enterprise_data --db $DB import-jobs --json jobs.json

# 5. 计算招聘指标（同公司同日期幂等）
uv run python -m local_tools.enterprise_data --db $DB metrics --company-id <id> --stat-date 2026-10-12

# 6. 查看企业画像
uv run python -m local_tools.enterprise_data --db $DB report --company-id <id>

# 7. 官网招聘页抽取（JSON-LD 优先，锚点兜底；ATS 页面标记需 Ego Lite）
uv run python -m local_tools.enterprise_data --db $DB extract-careers \
  --company-id <id> --site <公司域名> --output /tmp/jobs-candidate.json
uv run python -m local_tools.enterprise_data --db $DB import-jobs --json /tmp/jobs-candidate.json

# 8. 职位去重分组与风险标签
uv run python -m local_tools.enterprise_data --db $DB dedupe-jobs --company-id <id>
uv run python -m local_tools.enterprise_data --db $DB label-jobs --company-id <id> --stat-date 2026-10-12

# 9. 招聘平台采集（Ego Lite，只读；公司搜索需要平台登录态）
uv run python -m local_tools.enterprise_data --db $DB collect-jobs \
  --company-id <id> --taskspace <Ego任务空间> \
  --search boss-search --query "公司名" --platform boss --output /tmp/jobs-candidate.json
uv run python -m local_tools.enterprise_data --db $DB import-jobs --json /tmp/jobs-candidate.json

# 10. 批量招聘强度对比（多公司 → 采集/入库/去重/标签/指标 → Markdown 报告）
uv run python -m local_tools.enterprise_data --db $DB hiring-batch \
  --taskspace <Ego任务空间> \
  --target 微吼 --target 小鹅通 --target 创客匠人 \
  --platform liepin --platform boss --max-jobs 20 \
  --output /path/to/hiring-comparison.md
```

## 招聘平台采集（Ego Lite）

- 执行器：`ego_jobs`（zsh 包装器）+ `ego_jobs.mjs`（页面上下文提取）+ `collect-jobs`（Python 入口）。
- 提取逻辑：在页面里定位职位链接（`/job/`、`job_detail`、`/apply/` 等），向上找“同时包含标题与薪资/城市/招 N 人信号”的容器，输出标题、城市、薪资文本、招聘人数与链接。
- 已内置搜索模板：`boss-search`、`zhaopin-search`、`liepin-search`（`--search <模板> --query <公司名>`）。
- 雇主识别：从职位卡片提取招聘公司名（BOSS 的 `.boss-name`、通用 `company-name` 类）写入 `employer_name`；`--employer-filter <关键词>` 用来剔除劳务中介等非目标雇主职位（雇主为空时保守保留）。
- 实测：BOSS 直聘未登录时能渲染通用职位列表并成功提取（12 条）；但**按公司名搜索需要登录态**（BOSS/智联直链搜索会跳回通用列表），需先在 Ego Lite 里登录一次对应平台。
- 实测（登录后）：中兴通讯在 BOSS 抓到 30 条（工厂普工为主，薪资被自定义字体遮挡）、猎聘抓到 30 条（研发/职能岗，含 20-50k 薪资）；两平台合计 60 条，去重后 59 组（1 组标题相近合并，待人工复核）。
- 批量报告口径：`hiring-batch` 按品牌名做雇主过滤（company_id 前缀 `brand-`、身份标注 `brand_unverified`）；品牌名可能与其他公司重名（例如“云学堂”），正式使用前应把品牌映射到工商主体全名再复核。
- 已知限制：BOSS 的薪资用自定义字体渲染，文本提取常为空；招聘人数仅在页面明确写“招 N 人”时可取。

## 招聘数据（官网来源）

- 入口发现：从公司首页找招聘/ATS 链接，优先级为「第三方招聘系统 > 加入我们/招贤纳士等文案 > careers/jobs 路径 > 其他关键词」。
- 职位抽取：优先 schema.org `JobPosting` 的 JSON-LD；无 JSON-LD 时用职位关键词白名单 + 导航词黑名单过滤锚点，并识别“招 N 人”。
- ATS 识别：Moka / 北森 / 大易 / BOSS / 51job / 智联 / 猎聘 / 拉勾。ATS 厂商首页不是职位列表，会标记 `ats_render_required`，提示改用 Ego Lite 渲染后抽取（避免把营销页导航当职位）。
- 实测发现：国内企业（含保利威）普遍把职位放在第三方 ATS（如 Moka），HTML 直采受限，需要 Ego Lite 渲染；这条在 `_extraction.warnings` 中明确提示。
- 去重规则：同公司 + 同城市 + 标题相似度 ≥ 0.85 合并为一个招聘需求组；招聘人数按组内各来源**最大值**聚合（不叠加），置信度标注 single_source/consistent/mixed；标题不完全一致时 `review_status=pending` 待人工确认。
- 风险标签：`LONG_RUNNING`（在招 ≥60 天）、`POSSIBLE_STALE`、`POSSIBLE_OUTSOURCING`（标题/描述含外包、驻场、派遣、劳务）、`CLOSED_OR_UNAVAILABLE`；只打标不删除。
- 指标联动：`unique_job_count` 按去重组计数；`explicit_hiring_slots` 用去重后人数；`outsourcing_job_ratio` 基于标签计算。

## 年报 PDF 抽取

```bash
uv run python -m local_tools.enterprise_data --db $DB extract-annual-report \
  --pdf /path/to/annual-report.pdf \
  --company-id <id> --fiscal-year 2025 --period-end 2025-12-31 \
  --output /tmp/financial-candidate.json

# 复核候选 JSON 后入库
uv run python -m local_tools.enterprise_data --db $DB import-financial --json /tmp/financial-candidate.json
```

抽取规则（第一版，只支持带文本层的 PDF）：

- 员工人数：识别“在职员工的数量合计 / 员工共 N 人 / 员工总数 / 员工数量”等合计类表述；
  自动排除“母公司 / 主要子公司 / 劳务外包”口径。
- 资产总计：从“合并资产负债表 / 资产负债表”中取“资产总计”，优先合并口径；
  同时存在母公司报表时提示人工复核。
- 金额单位：识别“单位：千元 / 人民币千元”等标注，`total_assets` 统一换算为元入库，
  `unit_original` 保留报表原始单位；单位缺失时不换算并告警。
- 每个字段带 evidence（页码 + 原文摘录 + 置信度），输出含 `_extraction.warnings` 与
  `needs_review: true`，提示人工复核后再入库。

已验证样本：`polyv-radar-data/enterprise/samples/zte-2025-annual.pdf`（中兴通讯 2025 年报，249 页），
抽取结果：员工 65,095 人、总资产 217,739,375 千元 → 217,739,375,000.00 元（合并口径）。

## 最小字段

- `import-company`：`company_name`（必填）、`company_id`、`unified_social_credit_code`、`ticker`、`exchange`、
  `listing_status`、`province`、`city`、`industries[]`（standard/code/name/is_primary）
- `import-financial`：`company_id`、`fiscal_year`、`reporting_scope`、`report_version`、`period_end`、
  `employee_count`、`employee_count_type`（year_end/average）、`employee_count_scope`（consolidated/parent）、
  `total_assets`、`currency`、`unit_original`、`total_assets_scope`、`report_url`、可选 `evidence[]`
- `import-jobs`：`company_id` + `jobs[]`，每条含 `platform`、`platform_job_id`、`job_title`、`city`、
  `publish_date`、`first_seen_at`、`recruitment_count`、`raw_hiring_text`、`job_status`

## 计算规则（对应设计文档第 5 章）

- 增长率：`(本期 - 上期) / 上期`；上年为 0 记 `zero_base`，缺值记 `missing`，口径不一致记 `not_comparable`（不产出正式同比）。
- 口径可比性：员工/资产的统计范围（合并/母公司）与统计类型（年末/平均）必须一致，且需存在上一财年记录。
- 规模分层：员工 1–9/10–99/100–999/≥1000 与资产 500 万/5,000 万/5 亿 阈值分别打标，不合并成单一标签。
- 招聘活动指数：新增职位 30% + 明确人数 25% + 近期活跃 20% + 平台广度 15% + 需求多样性 10%；缺失维度重新归一化，不按 0 计。

## 数据完整性

- 财务与职位导入前校验 `company_id` 必须存在，避免孤儿数据。
- 财务唯一键：`company_id + fiscal_year + reporting_scope + report_version`；职位唯一键：`platform + platform_job_id`。
- 证据表 `data_evidence` 通过 `entity_type/entity_id` 关联，保留来源链接、页码、原文摘录与置信度。

## 下一步（未实现）

- 扫描件 OCR（PaddleOCR）与表格结构解析（pdfplumber/Camelot）增强。
- Ego Lite 版 ATS 职位抽取（Moka/北森/大易等 JS 渲染页面）。
- 企查查招聘 API（ApiCode 718）PoC → 生成 `import-jobs` 的候选 JSON。
