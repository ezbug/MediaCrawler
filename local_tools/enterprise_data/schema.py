"""SQLite 表结构（对应设计文档第 4 章的数据模型）。"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = "1.0"

DDL = """
CREATE TABLE IF NOT EXISTS company (
  company_id TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  company_name_normalized TEXT,
  unified_social_credit_code TEXT,
  registration_number TEXT,
  ticker TEXT,
  exchange TEXT,
  lei TEXT,
  country_code TEXT,
  province TEXT,
  city TEXT,
  registered_address TEXT,
  established_date TEXT,
  company_status TEXT,
  listing_status TEXT,
  parent_company_id TEXT,
  identity_match_status TEXT DEFAULT 'unverified',
  created_at TEXT,
  updated_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_credit
  ON company(unified_social_credit_code)
  WHERE unified_social_credit_code IS NOT NULL AND unified_social_credit_code != '';
CREATE INDEX IF NOT EXISTS idx_company_name ON company(company_name_normalized);

CREATE TABLE IF NOT EXISTS company_industry (
  industry_record_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  standard TEXT NOT NULL,
  standard_version TEXT,
  code TEXT,
  name TEXT,
  is_primary INTEGER DEFAULT 1,
  source TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_industry_company ON company_industry(company_id, standard);

CREATE TABLE IF NOT EXISTS company_financial_year (
  financial_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  period_end TEXT,
  reporting_scope TEXT DEFAULT 'consolidated',
  report_version TEXT NOT NULL DEFAULT '',
  employee_count INTEGER,
  employee_count_type TEXT,
  employee_count_scope TEXT,
  employee_count_date TEXT,
  total_assets TEXT,
  currency TEXT,
  unit_original TEXT,
  total_assets_scope TEXT,
  employee_growth_yoy REAL,
  employee_growth_status TEXT,
  asset_growth_yoy REAL,
  asset_growth_status TEXT,
  growth_comparability_status TEXT,
  size_by_employee TEXT,
  size_by_assets TEXT,
  size_legal_classification TEXT,
  report_url TEXT,
  created_at TEXT,
  updated_at TEXT,
  UNIQUE(company_id, fiscal_year, reporting_scope, report_version)
);
CREATE INDEX IF NOT EXISTS idx_financial_company ON company_financial_year(company_id, fiscal_year);

CREATE TABLE IF NOT EXISTS job_listing_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  company_id TEXT,
  platform TEXT NOT NULL,
  platform_job_id TEXT,
  job_url TEXT,
  job_title TEXT,
  job_title_normalized TEXT,
  city TEXT,
  district TEXT,
  job_level TEXT,
  department TEXT,
  publish_date TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  raw_hiring_text TEXT,
  recruitment_count INTEGER,
  dedup_group_id TEXT,
  job_status TEXT DEFAULT 'active',
  source_provider TEXT,
  data_license_scope TEXT,
  extraction_method TEXT,
  verification_status TEXT DEFAULT 'unverified',
  created_at TEXT,
  UNIQUE(platform, platform_job_id)
);
CREATE INDEX IF NOT EXISTS idx_job_company ON job_listing_snapshot(company_id, first_seen_at);

CREATE TABLE IF NOT EXISTS job_dedup_group (
  dedup_group_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  normalized_title TEXT,
  location_scope TEXT,
  source_job_ids TEXT,
  recruitment_count_deduped INTEGER,
  recruitment_count_raw_by_source TEXT,
  recruitment_count_confidence TEXT,
  recruitment_count_aggregation_method TEXT,
  dedup_confidence REAL,
  review_status TEXT DEFAULT 'pending',
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dedup_company ON job_dedup_group(company_id);

CREATE TABLE IF NOT EXISTS company_hiring_metrics (
  metric_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  stat_date TEXT NOT NULL,
  window_days INTEGER DEFAULT 30,
  active_job_count INTEGER,
  unique_job_count INTEGER,
  raw_listing_count INTEGER,
  new_job_count_30d INTEGER,
  closed_job_count_30d INTEGER,
  job_count_change_30d INTEGER,
  explicit_hiring_slots INTEGER,
  hiring_count_coverage REAL,
  median_job_age_days REAL,
  multi_platform_presence INTEGER,
  outsourcing_job_ratio REAL,
  hiring_activity_score REAL,
  data_coverage REAL,
  created_at TEXT,
  UNIQUE(company_id, stat_date, window_days)
);

CREATE TABLE IF NOT EXISTS data_evidence (
  evidence_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field_name TEXT,
  source_type TEXT,
  source_url TEXT,
  source_provider TEXT,
  source_page TEXT,
  source_excerpt TEXT,
  extraction_method TEXT,
  extraction_confidence REAL,
  observed_at TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_entity ON data_evidence(entity_type, entity_id);
"""


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(DDL)
    _ensure_columns(connection)
    connection.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION.split('.')[0])}")
    connection.commit()


def _ensure_columns(connection: sqlite3.Connection) -> None:
    """增量迁移：为既有数据库补齐后加的列。"""
    additions = {
        "job_listing_snapshot": {"staleness_label": "TEXT"},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
