"""美股 20-F 财务与员工数据（SEC XBRL + 20-F 正文）。

资产总计取 SEC XBRL companyconcept（us-gaap/Assets，年度 20-F）；员工人数取
20-F 正文的公开披露句子。产出与 import-financial 兼容的 JSON，含来源链接与原文。
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

UA = "POLYV enterprise research (contact: bugbgw8@gmail.com)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{concept}.json"
ARCHIVE_DIR = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/"


def _get(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                chunks: list[bytes] = []
                while True:
                    try:
                        chunk = response.read(1 << 20)
                    except Exception as exc:  # noqa: BLE001 - 大文件分块读取可能中断
                        partial = getattr(exc, "partial", b"") or b""
                        if partial:
                            chunks.append(partial)
                        if chunks:
                            break
                        raise
                    if not chunk:
                        break
                    chunks.append(chunk)
                data = b"".join(chunks)
                if data:
                    return data
                raise RuntimeError("空响应")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}（{last}）")


def lookup_cik(ticker: str) -> int:
    table = json.loads(_get(TICKERS_URL).decode("utf-8", "ignore"))
    for row in table.values():
        if str(row.get("ticker", "")).upper() == ticker.upper():
            return int(row["cik_str"])
    raise ValueError(f"未找到 ticker：{ticker}")


def annual_values(cik: int, concept: str = "us-gaap/Assets") -> dict[str, dict]:
    payload = json.loads(_get(CONCEPT_URL.format(cik=f"{cik:010d}", concept=concept)).decode("utf-8", "ignore"))
    values: dict[str, dict] = {}
    for unit_rows in (payload.get("units") or {}).values():
        for row in unit_rows:
            if row.get("form") not in {"20-F", "10-K"} or row.get("fp") != "FY":
                continue
            end = str(row.get("end") or "")
            if not end:
                continue
            current = values.get(end)
            if current is None or int(row.get("val") or 0):
                values.setdefault(end, row)
    return values


def filing_index(cik: int, accn: str) -> list[str]:
    directory = ARCHIVE_DIR.format(cik=cik, accn=accn.replace("-", ""))
    payload = json.loads(_get(directory + "index.json").decode("utf-8", "ignore"))
    return [directory + item["name"] for item in payload.get("directory", {}).get("item", [])
            if str(item.get("name", "")).lower().endswith((".htm", ".html"))]


MONTHS = {name: index for index, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
DATE_EN = r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})"
EMPLOYEE_MULTI = re.compile(
    r"([\d,]+)\s*,\s*([\d,]+)\s*and\s*([\d,]+)\s+(?:full-time\s+)?employees\s+as of\s+"
    + DATE_EN + r"\s*,\s*" + DATE_EN + r"\s*and\s*" + DATE_EN,
    re.I,
)
EMPLOYEE_SINGLE = re.compile(
    r"(?:approximately\s+|a total of\s+|had\s+)?([\d,]{3,})\s+(?:full-time\s+)?employees"
    r"(?:\s+as of\s+" + DATE_EN + r")?",
    re.I,
)
EMPLOYEE_DATE_FIRST = re.compile(
    r"as of\s+" + DATE_EN + r"\s*,?\s*(?:we|the company|the group)?\s*had\s*"
    r"(?:a total of\s+|approximately\s+)?([\d,]{3,})\s+(?:full-time\s+)?employees",
    re.I,
)
NUM_ITEM = r"(?:\d{1,3}(?:,\d{3})+|\d{3,})"
EMPLOYEE_BLOCK = re.compile(
    r"had\s+(?:approximately\s+|a total of\s+)?"
    r"(" + NUM_ITEM + r"(?:\s*,\s*" + NUM_ITEM + r")*(?:\s*and\s*" + NUM_ITEM + r")?)"
    r"\s+(?:full-time\s+)?employees[^.]{0,140}?as of\s+([^.]{8,200}?)respectively",
    re.I,
)


def find_employees(text: str) -> dict[int, tuple[int, str]]:
    """按披露日期年份返回 {年份: (人数, 原文句子)}。"""
    found: dict[int, tuple[int, str]] = {}
    for match in EMPLOYEE_BLOCK.finditer(text):
        numbers = [int(item.replace(",", "")) for item in re.findall(NUM_ITEM, match.group(1))]
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", match.group(2))]
        excerpt = re.sub(r"\s+", " ", text[max(0, match.start() - 60): match.end() + 40]).strip()
        if len(numbers) == len(years):
            for year, value in zip(years, numbers):
                found.setdefault(year, (value, excerpt))
    for match in EMPLOYEE_MULTI.finditer(text):
        values = [int(match.group(i).replace(",", "")) for i in (1, 2, 3)]
        dates = [(int(match.group(4 + i * 3 + 2)), match.group(4 + i * 3 + 1)) for i in range(3)]
        excerpt = re.sub(r"\s+", " ", text[max(0, match.start() - 80): match.end() + 60]).strip()
        for value, (year, _month) in zip(values, dates):
            found.setdefault(year, (value, excerpt))
    for match in EMPLOYEE_SINGLE.finditer(text):
        value = int(match.group(1).replace(",", ""))
        if value < 100:
            continue
        year_text = match.group(4)
        year = int(year_text) if year_text and year_text.isdigit() else 0
        excerpt = re.sub(r"\s+", " ", text[max(0, match.start() - 100): match.end() + 60]).strip()
        if year:
            found.setdefault(year, (value, excerpt))
    for match in EMPLOYEE_DATE_FIRST.finditer(text):
        year_text = match.group(3)
        value = int(match.group(4).replace(",", ""))
        if value < 100:
            continue
        excerpt = re.sub(r"\s+", " ", text[max(0, match.start() - 60): match.end() + 60]).strip()
        if year_text.isdigit():
            found.setdefault(int(year_text), (value, excerpt))
    return found


def fetch_company(ticker: str, name: str, imports_dir: Path, years: tuple[int, ...] = (2025, 2024)) -> dict:
    cik = lookup_cik(ticker)
    assets = annual_values(cik)
    company_id = f"us-{ticker.lower()}"
    result: dict = {"ticker": ticker, "name": name, "company_id": company_id, "cik": cik, "years": {}}
    employee_cache: dict[str, tuple[int, str]] = {}
    for end, row in sorted(assets.items(), reverse=True):
        fiscal_year = int(end[:4])
        if fiscal_year not in years:
            continue
        accn = str(row.get("accn") or "")
        directory = ARCHIVE_DIR.format(cik=cik, accn=accn.replace("-", ""))
        if accn not in employee_cache:
            try:
                docs = filing_index(cik, accn)
                primary = next((url for url in docs if re.search(r"20-?f", url, re.I)), docs[0] if docs else "")
                html = _get(primary, timeout=120).decode("utf-8", "ignore")
                text = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"&nbsp;?", " ", text)
                mapping = find_employees(text)
                employee_cache[accn] = mapping.get(fiscal_year) or mapping.get(0) or (0, "")
            except Exception as exc:  # noqa: BLE001
                employee_cache[accn] = (0, f"error: {exc}")
        employees, excerpt = employee_cache[accn]
        payload = {
            "company_id": company_id,
            "fiscal_year": fiscal_year,
            "period_end": end,
            "reporting_scope": "consolidated",
            "report_version": f"20f-{fiscal_year}",
            "employee_count": employees or None,
            "employee_count_type": "year_end",
            "employee_count_scope": "consolidated",
            "total_assets": f"{float(row['val']):.2f}",
            "currency": str(row.get("units") or "USD"),
            "unit_original": "USD",
            "total_assets_scope": "consolidated",
            "report_url": directory,
            "evidence": [
                {"field_name": "total_assets", "source_type": "sec-xbrl", "source_url": directory,
                 "source_page": f"20-F FY{fiscal_year} Assets",
                 "source_excerpt": f"us-gaap:Assets = {row['val']} (end {end}, accn {accn})",
                 "extraction_method": "sec-xbrl", "extraction_confidence": 0.95},
            ],
        }
        if employees:
            payload["evidence"].append({
                "field_name": "employee_count", "source_type": "sec-20f", "source_url": directory,
                "source_page": "20-F 员工章节", "source_excerpt": excerpt,
                "extraction_method": "sec-20f-text", "extraction_confidence": 0.9,
            })
        out = imports_dir / f"{company_id}-{fiscal_year}-annual.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["years"][str(fiscal_year)] = {
            "period_end": end, "employee_count": employees or None,
            "total_assets": payload["total_assets"], "currency": payload["currency"], "import_json": str(out),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="美股 20-F 财务与员工数据")
    parser.add_argument("--company", action="append", required=True, help="ticker=中文名，可重复")
    parser.add_argument("--imports", required=True)
    args = parser.parse_args(argv)
    imports_dir = Path(args.imports)
    imports_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for item in args.company:
        ticker, _, name = item.partition("=")
        try:
            results.append(fetch_company(ticker.strip(), name.strip() or ticker.strip(), imports_dir))
        except Exception as exc:  # noqa: BLE001
            results.append({"ticker": ticker, "status": "error", "error": str(exc)[:200]})
    out = imports_dir / "sec-fetch-summary.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
