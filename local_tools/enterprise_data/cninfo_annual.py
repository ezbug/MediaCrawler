"""巨潮资讯网年度报告下载与字段抽取（A股）。

只使用公开披露接口：公司检索 → 年度报告公告 → PDF 下载 → pdf_extract 抽取
员工人数与资产总计，产出与 import-financial 兼容的 JSON，并保留来源 URL。
只读公开信息，不登录、不破解；对接口限流做了间隔与重试。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .pdf_extract import extract_annual_report

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC = "http://static.cninfo.com.cn/"


def _post(url: str, data: dict, referer: str = "http://www.cninfo.com.cn/", retries: int = 3) -> dict:
    body = urllib.parse.urlencode(data).encode()
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except Exception as exc:  # noqa: BLE001 - 保留最后一次错误
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"接口请求失败：{url}（{last}）")


def resolve_org(keyword: str) -> list[dict]:
    rows = _post(SEARCH_URL, {"keyWord": keyword, "maxNum": "10"})
    return [
        {"code": str(row.get("code") or ""), "org_id": str(row.get("orgId") or ""),
         "name": str(row.get("zwjc") or row.get("pinyin") or "")}
        for row in rows or []
    ]


def query_annual(code: str, org_id: str, plate: str, year: int) -> list[dict]:
    """返回该财年年度报告公告（排除摘要/英文/更正类）。"""
    data = {
        "stock": f"{code},{org_id}", "tabName": "fulltext", "pageSize": "30", "pageNum": "1",
        "column": plate, "category": "category_ndbg_szsh", "plate": "sz" if plate == "szse" else "sh",
        "seDate": f"{year + 1}-01-01~{year + 1}-12-31", "searchkey": "", "secid": "",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    payload = _post(QUERY_URL, data, referer="http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice")
    rows = []
    for item in payload.get("announcements") or []:
        title = str(item.get("announcementTitle") or "").replace("<em>", "").replace("</em>", "")
        if "年度报告" not in title:
            continue
        if any(word in title for word in ("摘要", "英文", "更正", "补充", "问询", "说明", "取消", "提示性")):
            continue
        rows.append({
            "title": title,
            "url": STATIC + str(item.get("adjunctUrl") or ""),
            "published_at": time.strftime("%Y-%m-%d", time.localtime(int(item.get("announcementTime") or 0) / 1000)),
        })
    return rows


def download(url: str, dest: Path, retries: int = 3) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "http://www.cninfo.com.cn/"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
            if len(data) < 50_000:
                raise RuntimeError(f"文件过小：{len(data)} bytes")
            dest.write_bytes(data)
            return dest
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下载失败：{url}（{last}）")


def fetch_report(company: dict, year: int, samples_dir: Path, imports_dir: Path) -> dict:
    """下载并抽取一家公司某财年的年度报告，返回入库 JSON（含来源 URL）。"""
    code = str(company["ticker"])
    plate = "szse" if company.get("exchange") == "SZSE" else "sse"
    candidates = query_annual(code, company["org_id"], plate, year)
    if not candidates:
        return {"company_id": company["company_id"], "fiscal_year": year, "status": "not_found"}
    report = candidates[0]
    pdf_path = samples_dir / f"{company['company_id']}-{year}-annual.pdf"
    download(report["url"], pdf_path)
    payload = extract_annual_report(
        pdf_path, company_id=company["company_id"], fiscal_year=year,
        report_version=f"cninfo-annual-{year}", period_end=f"{year}-12-31",
    )
    payload["report_url"] = report["url"]
    payload["_extraction"]["source_title"] = report["title"]
    payload["_extraction"]["published_at"] = report["published_at"]
    for item in payload.get("evidence") or []:
        item["source_url"] = report["url"]
        item["source_type"] = "cninfo-annual-report"
    out = imports_dir / f"{company['company_id']}-{year}-annual.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["status"] = "ok"
    payload["import_json"] = str(out)
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="巨潮年报下载与抽取（A股）")
    parser.add_argument("--targets", required=True, help="目标公司 JSON（含 name/domain/ticker/exchange）")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2024])
    parser.add_argument("--samples", required=True)
    parser.add_argument("--imports", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))["companies"]
    samples_dir, imports_dir = Path(args.samples), Path(args.imports)
    results = []
    for index, company in enumerate(targets):
        if company.get("exchange") not in {"SZSE", "SSE"}:
            continue
        if args.limit and len(results) >= args.limit:
            break
        entry = {"name": company["name"], "ticker": company["ticker"]}
        try:
            orgs = resolve_org(company["name"])
            match = next((row for row in orgs if row["code"] == str(company["ticker"])), orgs[0] if orgs else None)
            if not match:
                orgs = resolve_org(str(company["ticker"]))
                match = next((row for row in orgs if row["code"] == str(company["ticker"])), orgs[0] if orgs else None)
            if not match:
                entry["status"] = "org_not_found"
                results.append(entry)
                continue
            company = {**company, "company_id": f"{company['exchange'].lower()}-{company['ticker']}", "org_id": match["org_id"]}
            entry["company_id"] = company["company_id"]
            for year in args.years:
                payload = fetch_report(company, year, samples_dir, imports_dir)
                entry[f"fy{year}"] = {
                    "status": payload.get("status"),
                    "employee_count": payload.get("employee_count"),
                    "total_assets": payload.get("total_assets"),
                    "warnings": (payload.get("_extraction") or {}).get("warnings"),
                }
                time.sleep(0.8)
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "error"
            entry["error"] = str(exc)[:200]
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))
    summary_path = imports_dir / "cninfo-fetch-summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"companies": len(results), "summary": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
