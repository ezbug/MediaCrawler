"""企业数据归纳系统的存储层（SQLite）。"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from . import schema
from .metrics import (
    COMPARABLE,
    GROWTH_OK,
    MISSING,
    NOT_COMPARABLE,
    ZERO_BASE,
    check_comparability,
    growth_rate,
    hiring_activity_score,
    size_by_assets,
    size_by_employee,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", str(title or "")).lower()


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class EnterpriseStore:
    """企业主数据 + 年报财务 + 招聘职位 + 证据的读写入口。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        schema.initialize(self.connection)

    def close(self) -> None:
        self.connection.close()

    # ---------------------------------------------------------------- company
    def upsert_company(self, payload: dict) -> str:
        credit = str(payload.get("unified_social_credit_code") or "").strip()
        company_id = str(payload.get("company_id") or "").strip()
        if not company_id and credit:
            existing = self.connection.execute(
                "SELECT company_id FROM company WHERE unified_social_credit_code = ?", (credit,)
            ).fetchone()
            company_id = existing["company_id"] if existing else ""
        company_id = company_id or _new_id()
        stamp = _now()
        existing = self.connection.execute("SELECT created_at FROM company WHERE company_id = ?", (company_id,)).fetchone()
        self.connection.execute(
            """
            INSERT INTO company (
              company_id, company_name, company_name_normalized, unified_social_credit_code,
              registration_number, ticker, exchange, lei, country_code, province, city,
              registered_address, established_date, company_status, listing_status,
              parent_company_id, identity_match_status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id) DO UPDATE SET
              company_name=excluded.company_name,
              company_name_normalized=excluded.company_name_normalized,
              unified_social_credit_code=excluded.unified_social_credit_code,
              registration_number=excluded.registration_number,
              ticker=excluded.ticker,
              exchange=excluded.exchange,
              lei=excluded.lei,
              country_code=excluded.country_code,
              province=excluded.province,
              city=excluded.city,
              registered_address=excluded.registered_address,
              established_date=excluded.established_date,
              company_status=excluded.company_status,
              listing_status=excluded.listing_status,
              parent_company_id=excluded.parent_company_id,
              identity_match_status=excluded.identity_match_status,
              updated_at=excluded.updated_at
            """,
            (
                company_id,
                str(payload.get("company_name") or "").strip(),
                _normalize_name(payload.get("company_name") or ""),
                credit or None,
                payload.get("registration_number"),
                payload.get("ticker"),
                payload.get("exchange"),
                payload.get("lei"),
                payload.get("country_code"),
                payload.get("province"),
                payload.get("city"),
                payload.get("registered_address"),
                payload.get("established_date"),
                payload.get("company_status"),
                payload.get("listing_status"),
                payload.get("parent_company_id"),
                str(payload.get("identity_match_status") or "unverified"),
                existing["created_at"] if existing else stamp,
                stamp,
            ),
        )
        self.connection.commit()
        return company_id

    def add_industry(self, company_id: str, payload: dict) -> str:
        record_id = str(payload.get("industry_record_id") or _new_id())
        self.connection.execute(
            """
            INSERT INTO company_industry (
              industry_record_id, company_id, standard, standard_version, code, name, is_primary, source, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(industry_record_id) DO UPDATE SET
              standard=excluded.standard, standard_version=excluded.standard_version,
              code=excluded.code, name=excluded.name, is_primary=excluded.is_primary, source=excluded.source
            """,
            (
                record_id,
                company_id,
                str(payload.get("standard") or "GB_T_4754"),
                payload.get("standard_version"),
                payload.get("code"),
                payload.get("name"),
                1 if payload.get("is_primary", True) else 0,
                payload.get("source"),
                _now(),
            ),
        )
        self.connection.commit()
        return record_id

    # --------------------------------------------------------------- financial
    def _require_company(self, company_id: str) -> None:
        row = self.connection.execute("SELECT 1 FROM company WHERE company_id = ?", (company_id,)).fetchone()
        if row is None:
            raise ValueError(f"company_id 不存在，请先 import-company：{company_id}")

    def _previous_financial(self, company_id: str, fiscal_year: int, reporting_scope: str) -> dict | None:
        row = self.connection.execute(
            """
            SELECT * FROM company_financial_year
            WHERE company_id = ? AND reporting_scope = ? AND fiscal_year = ?
            ORDER BY report_version DESC, updated_at DESC LIMIT 1
            """,
            (company_id, reporting_scope, int(fiscal_year) - 1),
        ).fetchone()
        return _row(row)

    def upsert_financial(self, payload: dict) -> dict:
        company_id = str(payload.get("company_id") or "").strip()
        if not company_id:
            raise ValueError("import-financial 需要 company_id")
        self._require_company(company_id)
        fiscal_year = int(payload.get("fiscal_year"))
        reporting_scope = str(payload.get("reporting_scope") or "consolidated")
        report_version = str(payload.get("report_version") or "")

        previous = self._previous_financial(company_id, fiscal_year, reporting_scope)
        employee_now = _to_int(payload.get("employee_count"))
        assets_now = _to_float(payload.get("total_assets"))
        employee_prev = previous.get("employee_count") if previous else None
        assets_prev = _to_float(previous.get("total_assets")) if previous else None

        employee_growth, employee_status = growth_rate(employee_now, employee_prev)
        asset_growth, asset_status = growth_rate(assets_now, assets_prev)

        employee_comp = check_comparability(
            scope_now=payload.get("employee_count_scope"),
            scope_prev=(previous or {}).get("employee_count_scope"),
            type_now=payload.get("employee_count_type"),
            type_prev=(previous or {}).get("employee_count_type"),
        )
        asset_comp = check_comparability(
            scope_now=payload.get("total_assets_scope"),
            scope_prev=(previous or {}).get("total_assets_scope"),
            type_now=None,
            type_prev=None,
        )
        if previous is None:
            employee_comp = asset_comp = NOT_COMPARABLE
        if employee_comp != COMPARABLE:
            employee_growth, employee_status = None, NOT_COMPARABLE if previous else MISSING
        if asset_comp != COMPARABLE:
            asset_growth, asset_status = None, NOT_COMPARABLE if previous else MISSING

        if employee_comp != COMPARABLE or asset_comp != COMPARABLE:
            overall = NOT_COMPARABLE if previous else MISSING
        elif employee_status == ZERO_BASE or asset_status == ZERO_BASE:
            overall = ZERO_BASE
        elif employee_status == GROWTH_OK and asset_status == GROWTH_OK:
            overall = COMPARABLE
        else:
            overall = "partial"

        stamp = _now()
        existing = self.connection.execute(
            """
            SELECT financial_id, created_at FROM company_financial_year
            WHERE company_id = ? AND fiscal_year = ? AND reporting_scope = ? AND report_version = ?
            """,
            (company_id, fiscal_year, reporting_scope, report_version),
        ).fetchone()
        financial_id = existing["financial_id"] if existing else _new_id()

        self.connection.execute(
            """
            INSERT INTO company_financial_year (
              financial_id, company_id, fiscal_year, period_end, reporting_scope, report_version,
              employee_count, employee_count_type, employee_count_scope, employee_count_date,
              total_assets, currency, unit_original, total_assets_scope,
              employee_growth_yoy, employee_growth_status, asset_growth_yoy, asset_growth_status,
              growth_comparability_status, size_by_employee, size_by_assets, size_legal_classification,
              report_url, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id, fiscal_year, reporting_scope, report_version) DO UPDATE SET
              period_end=excluded.period_end,
              employee_count=excluded.employee_count,
              employee_count_type=excluded.employee_count_type,
              employee_count_scope=excluded.employee_count_scope,
              employee_count_date=excluded.employee_count_date,
              total_assets=excluded.total_assets,
              currency=excluded.currency,
              unit_original=excluded.unit_original,
              total_assets_scope=excluded.total_assets_scope,
              employee_growth_yoy=excluded.employee_growth_yoy,
              employee_growth_status=excluded.employee_growth_status,
              asset_growth_yoy=excluded.asset_growth_yoy,
              asset_growth_status=excluded.asset_growth_status,
              growth_comparability_status=excluded.growth_comparability_status,
              size_by_employee=excluded.size_by_employee,
              size_by_assets=excluded.size_by_assets,
              size_legal_classification=excluded.size_legal_classification,
              report_url=excluded.report_url,
              updated_at=excluded.updated_at
            """,
            (
                financial_id, company_id, fiscal_year, payload.get("period_end"), reporting_scope, report_version,
                employee_now, payload.get("employee_count_type"), payload.get("employee_count_scope"), payload.get("employee_count_date"),
                None if assets_now is None else str(payload.get("total_assets")), payload.get("currency"), payload.get("unit_original"), payload.get("total_assets_scope"),
                employee_growth, employee_status, asset_growth, asset_status,
                overall, size_by_employee(employee_now), size_by_assets(assets_now), payload.get("size_legal_classification"),
                payload.get("report_url"), existing["created_at"] if existing else stamp, stamp,
            ),
        )
        for item in payload.get("evidence") or []:
            self.add_evidence("company_financial_year", financial_id, item)
        self.connection.commit()
        return {
            "financial_id": financial_id,
            "company_id": company_id,
            "fiscal_year": fiscal_year,
            "employee_growth_yoy": employee_growth,
            "employee_growth_status": employee_status,
            "asset_growth_yoy": asset_growth,
            "asset_growth_status": asset_status,
            "growth_comparability_status": overall,
            "size_by_employee": size_by_employee(employee_now),
            "size_by_assets": size_by_assets(assets_now),
        }

    # ------------------------------------------------------------------- jobs
    def add_jobs(self, company_id: str, jobs: list[dict]) -> dict:
        if company_id:
            self._require_company(company_id)
        inserted = updated = 0
        for job in jobs:
            platform = str(job.get("platform") or "").strip()
            platform_job_id = str(job.get("platform_job_id") or "").strip()
            if not platform:
                raise ValueError("职位缺少 platform")
            existing = None
            if platform_job_id:
                existing = self.connection.execute(
                    "SELECT snapshot_id, first_seen_at FROM job_listing_snapshot WHERE platform = ? AND platform_job_id = ?",
                    (platform, platform_job_id),
                ).fetchone()
            stamp = _now()
            first_seen = existing["first_seen_at"] if existing else str(job.get("first_seen_at") or stamp)
            snapshot_id = existing["snapshot_id"] if existing else _new_id()
            self.connection.execute(
                """
                INSERT INTO job_listing_snapshot (
                  snapshot_id, company_id, platform, platform_job_id, job_url, job_title, job_title_normalized,
                  city, district, job_level, department, employer_name, publish_date, first_seen_at, last_seen_at,
                  raw_hiring_text, recruitment_count, dedup_group_id, job_status, source_provider,
                  data_license_scope, extraction_method, verification_status, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                  job_url=excluded.job_url,
                  job_title=excluded.job_title,
                  job_title_normalized=excluded.job_title_normalized,
                  city=excluded.city,
                  district=excluded.district,
                  job_level=excluded.job_level,
                  department=excluded.department,
                  employer_name=excluded.employer_name,
                  publish_date=excluded.publish_date,
                  last_seen_at=excluded.last_seen_at,
                  raw_hiring_text=excluded.raw_hiring_text,
                  recruitment_count=excluded.recruitment_count,
                  dedup_group_id=excluded.dedup_group_id,
                  job_status=excluded.job_status,
                  source_provider=excluded.source_provider,
                  data_license_scope=excluded.data_license_scope,
                  extraction_method=excluded.extraction_method,
                  verification_status=excluded.verification_status
                """,
                (
                    snapshot_id, company_id, platform, platform_job_id or None, job.get("job_url"),
                    job.get("job_title"), _normalize_title(job.get("job_title")), job.get("city"), job.get("district"),
                    job.get("job_level"), job.get("department"), job.get("employer_name"), job.get("publish_date"), first_seen, stamp,
                    job.get("raw_hiring_text"), _to_int(job.get("recruitment_count")), job.get("dedup_group_id"),
                    str(job.get("job_status") or "active"), job.get("source_provider"), job.get("data_license_scope"),
                    job.get("extraction_method"), str(job.get("verification_status") or "unverified"), stamp,
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        self.connection.commit()
        return {"inserted": inserted, "updated": updated, "total": inserted + updated}

    def compute_hiring_metrics(self, company_id: str, stat_date: str, window_days: int = 30) -> dict:
        cutoff = (datetime.strptime(stat_date, "%Y-%m-%d") - timedelta(days=window_days)).date().isoformat()
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM job_listing_snapshot WHERE company_id = ?", (company_id,)
        )]
        active = [row for row in rows if (row.get("job_status") or "active") == "active"]
        new_jobs = [row for row in active if (row.get("first_seen_at") or "") >= cutoff]
        closed = [row for row in rows if (row.get("job_status") or "") == "CLOSED_OR_UNAVAILABLE"]
        groups = {
            row["dedup_group_id"]: dict(row)
            for row in self.connection.execute("SELECT * FROM job_dedup_group WHERE company_id = ?", (company_id,))
        }
        grouped_ids = {row.get("dedup_group_id") for row in active if row.get("dedup_group_id")}
        ungrouped = [row for row in active if not row.get("dedup_group_id")]
        unique_job_count = (len(grouped_ids) + len(ungrouped)) if groups else len(active)

        slots = 0
        has_slots = False
        covered = 0
        for group_id in grouped_ids:
            group = groups.get(group_id) or {}
            if group.get("recruitment_count_deduped") is not None:
                slots += int(group["recruitment_count_deduped"])
                has_slots = True
                covered += sum(1 for row in active if row.get("dedup_group_id") == group_id)
        for row in ungrouped:
            if row.get("recruitment_count") is not None:
                slots += int(row["recruitment_count"])
                has_slots = True
                covered += 1
        explicit_slots = slots if has_slots else None
        outsourcing = sum(1 for row in active if row.get("staleness_label") == "POSSIBLE_OUTSOURCING")
        labeled = any(row.get("staleness_label") for row in active)
        platforms = {row.get("platform") for row in active if row.get("platform")}
        titles = {row.get("job_title_normalized") for row in active if row.get("job_title_normalized")}
        ages = []
        for row in active:
            seen = row.get("first_seen_at") or ""
            if seen[:10]:
                try:
                    ages.append((datetime.strptime(stat_date, "%Y-%m-%d") - datetime.strptime(seen[:10], "%Y-%m-%d")).days)
                except ValueError:
                    pass
        subscores = {
            "new_jobs": min(100.0, len(new_jobs) * 10.0),
            "explicit_slots": min(100.0, float(explicit_slots)) if explicit_slots is not None else None,
            "activity": min(100.0, (len(new_jobs) / len(active) * 100.0) if active else 0.0),
            "platform_breadth": min(100.0, len(platforms) * 33.3),
            "diversity": min(100.0, len(titles) * 10.0) if titles else None,
        }
        score, score_meta = hiring_activity_score(subscores)
        metrics = {
            "company_id": company_id,
            "stat_date": stat_date,
            "window_days": window_days,
            "active_job_count": len(active),
            "unique_job_count": unique_job_count,
            "raw_listing_count": len(rows),
            "new_job_count_30d": len(new_jobs),
            "closed_job_count_30d": len(closed),
            # 净变化 = 窗口内新增 - 窗口内下线（需要连续快照才能精确，这里作为代理指标）
            "job_count_change_30d": len(new_jobs) - len(closed),
            "explicit_hiring_slots": explicit_slots,
            "hiring_count_coverage": (covered / len(active)) if active else None,
            "median_job_age_days": median(ages) if ages else None,
            "multi_platform_presence": len(platforms),
            "outsourcing_job_ratio": (outsourcing / len(active)) if (active and labeled) else None,
            "hiring_activity_score": score,
            "data_coverage": (covered / len(active)) if active else None,
        }
        self.connection.execute(
            """
            INSERT INTO company_hiring_metrics (
              metric_id, company_id, stat_date, window_days, active_job_count, unique_job_count,
              raw_listing_count, new_job_count_30d, closed_job_count_30d, job_count_change_30d,
              explicit_hiring_slots, hiring_count_coverage, median_job_age_days, multi_platform_presence,
              outsourcing_job_ratio, hiring_activity_score, data_coverage, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id, stat_date, window_days) DO UPDATE SET
              active_job_count=excluded.active_job_count,
              unique_job_count=excluded.unique_job_count,
              raw_listing_count=excluded.raw_listing_count,
              new_job_count_30d=excluded.new_job_count_30d,
              closed_job_count_30d=excluded.closed_job_count_30d,
              job_count_change_30d=excluded.job_count_change_30d,
              explicit_hiring_slots=excluded.explicit_hiring_slots,
              hiring_count_coverage=excluded.hiring_count_coverage,
              median_job_age_days=excluded.median_job_age_days,
              multi_platform_presence=excluded.multi_platform_presence,
              outsourcing_job_ratio=excluded.outsourcing_job_ratio,
              hiring_activity_score=excluded.hiring_activity_score,
              data_coverage=excluded.data_coverage
            """,
            (
                _new_id(), company_id, stat_date, window_days, metrics["active_job_count"], metrics["unique_job_count"],
                metrics["raw_listing_count"], metrics["new_job_count_30d"], metrics["closed_job_count_30d"],
                metrics["job_count_change_30d"], metrics["explicit_hiring_slots"], metrics["hiring_count_coverage"],
                metrics["median_job_age_days"], metrics["multi_platform_presence"], metrics["outsourcing_job_ratio"],
                metrics["hiring_activity_score"], metrics["data_coverage"], _now(),
            ),
        )
        self.connection.commit()
        metrics["score_meta"] = score_meta
        return metrics

    # --------------------------------------------------------------- evidence
    def add_evidence(self, entity_type: str, entity_id: str, payload: dict) -> str:
        evidence_id = str(payload.get("evidence_id") or _new_id())
        self.connection.execute(
            """
            INSERT INTO data_evidence (
              evidence_id, entity_type, entity_id, field_name, source_type, source_url, source_provider,
              source_page, source_excerpt, extraction_method, extraction_confidence, observed_at, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                evidence_id, entity_type, entity_id, payload.get("field_name"), payload.get("source_type"),
                payload.get("source_url"), payload.get("source_provider"), payload.get("source_page"),
                payload.get("source_excerpt"), payload.get("extraction_method"),
                _to_float(payload.get("extraction_confidence")), payload.get("observed_at"), _now(),
            ),
        )
        self.connection.commit()
        return evidence_id

    # ---------------------------------------------------------------- reports
    def company_profile(self, company_id: str) -> dict:
        company = _row(self.connection.execute("SELECT * FROM company WHERE company_id = ?", (company_id,)).fetchone())
        industries = [dict(row) for row in self.connection.execute(
            "SELECT * FROM company_industry WHERE company_id = ? ORDER BY is_primary DESC", (company_id,)
        )]
        financials = [dict(row) for row in self.connection.execute(
            "SELECT * FROM company_financial_year WHERE company_id = ? ORDER BY fiscal_year DESC, reporting_scope", (company_id,)
        )]
        hiring = _row(self.connection.execute(
            "SELECT * FROM company_hiring_metrics WHERE company_id = ? ORDER BY stat_date DESC LIMIT 1", (company_id,)
        ).fetchone())
        evidence_count = self.connection.execute(
            "SELECT COUNT(*) AS n FROM data_evidence WHERE entity_id IN (SELECT financial_id FROM company_financial_year WHERE company_id = ?)",
            (company_id,),
        ).fetchone()["n"]
        return {
            "company": company,
            "industries": industries,
            "financials": financials,
            "hiring_metrics": hiring,
            "evidence_count": evidence_count,
        }

    def list_companies(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT company_id, company_name, ticker, exchange, listing_status, city FROM company ORDER BY company_name"
        )]
