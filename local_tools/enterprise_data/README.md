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
```

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

- 年报 PDF 抽取（PyMuPDF/pdfplumber/PaddleOCR）→ 生成 `import-financial` 的候选 JSON。
- 企查查招聘 API（ApiCode 718）PoC → 生成 `import-jobs` 的候选 JSON。
- 跨平台职位去重（job_dedup_group 的自动合并与置信度）与僵尸职位标签联动。
