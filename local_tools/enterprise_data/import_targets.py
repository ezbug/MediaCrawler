"""把目标公司清单与已抽取的财报 JSON 导入企业库（幂等）。

用法：
    uv run python -m local_tools.enterprise_data.import_targets \\
        --db <enterprise.sqlite3> --targets <targets.json> --imports <imports 目录>

公司按 company_id 幂等写入；财报按 (company_id, fiscal_year, scope, version) 幂等写入。
缺失字段（员工数或资产）会记录但不会伪造数值。
"""
from __future__ import annotations

import json
from pathlib import Path

from .storage import EnterpriseStore


def company_id_for(company: dict) -> str:
    exchange = str(company.get("exchange") or "").upper()
    if exchange in {"SZSE", "SSE"}:
        return f"{exchange.lower()}-{company['ticker']}"
    if exchange in {"NYSE", "NASDAQ"}:
        return f"us-{str(company['ticker']).lower()}"
    return f"{exchange.lower()}-{company['ticker']}" if exchange else str(company["ticker"])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="导入目标公司与财报")
    parser.add_argument("--db", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--imports", required=True)
    parser.add_argument("--years", nargs="+", type=int, default=[2024, 2025])
    args = parser.parse_args(argv)

    store = EnterpriseStore(args.db)
    imports_dir = Path(args.imports)
    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))["companies"]
    results = []
    try:
        for company in targets:
            company_id = company_id_for(company)
            store.upsert_company({
                "company_id": company_id,
                "company_name": company["name"],
                "ticker": str(company.get("ticker") or ""),
                "exchange": company.get("exchange") or "",
                "listing_status": "listed",
                "industries": [],
            })
            if company.get("industry"):
                store.add_industry(company_id, {"name": company["industry"], "is_primary": True})
            entry = {"company_id": company_id, "name": company["name"], "years": {}}
            for year in args.years:
                path = imports_dir / f"{company_id}-{year}-annual.json"
                if not path.exists():
                    entry["years"][str(year)] = {"status": "import_missing"}
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["company_id"] = company_id
                payload.setdefault("fiscal_year", year)
                try:
                    stored = store.upsert_financial(payload)
                    entry["years"][str(year)] = {
                        "status": "ok", "employee_count": payload.get("employee_count"),
                        "total_assets": payload.get("total_assets"), "currency": payload.get("currency"),
                        "employee_growth": stored.get("employee_growth_status"),
                        "asset_growth": stored.get("asset_growth_status"),
                    }
                except Exception as exc:  # noqa: BLE001
                    entry["years"][str(year)] = {"status": "error", "error": str(exc)[:160]}
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False))
    finally:
        store.close()
    ok = sum(1 for row in results for data in row["years"].values() if data.get("status") == "ok")
    print(json.dumps({"companies": len(results), "financial_rows": ok}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
