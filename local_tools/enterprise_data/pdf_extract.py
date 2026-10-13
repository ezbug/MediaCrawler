"""年报 PDF 抽取（第一版：文本层解析，产出候选 JSON，需人工复核）。

只处理带文本层的 PDF；扫描件留待 OCR（PaddleOCR）阶段。
输出与 import-financial 兼容的 JSON，并附带 evidence[] 与 _extraction 元数据。

重要口径规则（来自设计文档）：
- 母公司在职员工数量不等于集团员工总数，两者不得混用；本抽取只取“合计”类关键词。
- 资产总计同时出现在合并报表与母公司报表时，优先取合并口径，并提示人工复核。
- 单位缺失时不做默认换算，只记录原始值与单位状态。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

EMPLOYEE_LABELS = (
    "在职员工的数量合计", "在职员工数量合计",
    "在职员工总数", "员工数量合计", "员工总数", "员工共", "在职员工", "员工人数", "员工数量", "雇员",
    "共有员工",
)
EMPLOYEE_STRONG_LABELS = ("在职员工的数量合计", "在职员工数量合计")
EMPLOYEE_EXCLUDE_KEYWORDS = ("母公司", "主要子公司", "劳务外包", "员工持股", "退休", "薪酬")
EMPLOYEE_WEAK_EXCLUDE_KEYWORDS = ("持股", "认购", "预留", "激励", "离职", "退休", "薪酬", "派遣", "外包", "子公司")
ASSET_LABELS = ("资产总计", "资产总额")
UNIT_PATTERNS = (
    re.compile(r"单位\s*[为是]?\s*[:：]\s*(?:人民币)?\s*(百万元|千元|万元|元)"),
    re.compile(r"单位\s*[:：]\s*(百万元|千元|万元|元)"),
    re.compile(r"人民币(百万元|千元|万元|元)"),
)
UNIT_FACTORS = {"元": 1, "千元": 1_000, "万元": 10_000, "百万元": 1_000_000}
NUMBER_PATTERN = re.compile(r"\d[\d,，]*(?:\.\d+)?")


def read_pages(pdf_path: str | Path) -> list[dict]:
    """返回 [{page, text}]；page 为 1 起的物理页码。"""
    document = pymupdf.open(str(pdf_path))
    pages = []
    try:
        for index, page in enumerate(document):
            pages.append({"page": index + 1, "text": page.get_text("text")})
    finally:
        document.close()
    return pages


def _first_number_after(text: str, start: int, window: int = 90) -> str | None:
    match = NUMBER_PATTERN.search(text[start : start + window])
    return match.group(0) if match else None


def _excerpt(text: str, start: int, end: int, radius: int = 60) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius) : min(len(text), end + radius)]).strip()


def find_employee_candidates(pages: list[dict]) -> list[dict]:
    candidates = []
    for page in pages:
        text = page["text"]
        spans = []
        for priority, label in enumerate(EMPLOYEE_LABELS):
            for match in re.finditer(re.escape(label), text):
                spans.append((match.start(), match.end(), label, priority))
        spans.sort(key=lambda item: (item[0], item[3], -(item[1] - item[0])))
        claimed: list[tuple[int, int]] = []
        for start, end, label, _priority in spans:
            if any(not (end <= claimed_start or start >= claimed_end) for claimed_start, claimed_end in claimed):
                continue  # 与更高优先级模式重叠
            line_start = text.rfind("\n", 0, start) + 1
            prefix = text[max(line_start, start - 18) : start]
            if any(bad in prefix for bad in EMPLOYEE_EXCLUDE_KEYWORDS):
                continue
            if label == "员工共":
                weak_prefix = text[max(line_start, start - 40) : start]
                if any(bad in weak_prefix for bad in EMPLOYEE_WEAK_EXCLUDE_KEYWORDS):
                    continue
            tail = text[end : end + 60]
            number = re.search(r"(\d[\d,，]{1,})\s*(万人|千|人|名)?", tail)
            if not number:
                continue
            value_text = number.group(1).replace(",", "").replace("，", "")
            unit = (number.group(2) or "").strip()
            after = text[end + number.end() : end + number.end() + 3]
            if re.match(r"\s*%", after):
                continue
            if label == "员工共" and unit not in {"人", "名", "万人", "千"} and not re.match(r"\s*人", after):
                continue
            try:
                value = int(value_text)
            except ValueError:
                continue
            if unit == "万人":
                value *= 10_000
            elif unit == "千":
                value *= 1_000
            if re.match(r"\s*年", after) and 1900 <= value <= 2099:
                continue  # 年份误读
            weak = label not in EMPLOYEE_STRONG_LABELS
            if weak and unit not in {"人", "名", "万人", "千"}:
                continue  # 弱标签必须紧跟人数单位
            if value < 50:
                continue
            claimed.append((start, end))
            confidence = 0.95 if not weak else (0.85 if unit in {"人", "名"} else 0.75)
            candidates.append({
                "page": page["page"],
                "value": value,
                "keyword": label,
                "confidence": confidence,
                "excerpt": _excerpt(text, start, end + number.end() + 3),
            })
    return candidates


def _detect_scope(text: str, position: int, lookback: int = 20000) -> str:
    """合并报表标题为“合并资产负债表”；母公司报表标题可能是“资产负债表”或“母公司资产负债表”。"""
    window = text[max(0, position - lookback) : position]
    consolidated = window.rfind("合并资产负债表")
    statement = window.rfind("资产负债表")
    if consolidated >= 0 and statement >= 0 and statement - consolidated <= 2:
        return "consolidated"
    if statement >= 0:
        return "parent"
    return "unknown"


def _detect_unit(text: str, position: int, lookback: int = 20000) -> str | None:
    window = text[max(0, position - lookback) : position]
    found: list[tuple[int, str]] = []
    for pattern in UNIT_PATTERNS:
        for match in pattern.finditer(window):
            found.append((match.start(), match.group(1)))
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1]


def _convert_to_yuan(value_text: str, unit: str | None) -> str | None:
    """把报表原始数值换算为元；单位未知时原样保留并由告警提示人工确认。"""
    try:
        value = float(value_text.replace(",", "").replace("，", ""))
    except ValueError:
        return None
    factor = UNIT_FACTORS.get(unit or "", None)
    if factor is None:
        return value_text.replace("，", ",")
    return f"{value * factor:.2f}"


def find_asset_candidates(pages: list[dict]) -> list[dict]:
    candidates = []
    carry = ""
    for page in pages:
        text = page["text"]
        context = carry + text
        offset = len(carry)
        for label in ASSET_LABELS:
            for match in re.finditer(re.escape(label), context):
                if match.start() < offset:
                    continue  # 上一页的命中已处理
                number_text = _first_number_after(context, match.end(), window=80)
                if not number_text:
                    continue
                after = context[match.end() : match.end() + len(number_text) + 4]
                if "%" in after:
                    continue  # 内控评价比例等噪声
                prefix = context[max(0, match.start() - 30) : match.start()]
                if any(bad in prefix for bad in ("评价范围", "占比", "占公司", "潜在错报", "比例", "占期末")):
                    continue
                scope = _detect_scope(context, match.start())
                confidence = 0.9 if scope == "consolidated" else (0.5 if scope == "parent" else 0.35)
                candidates.append({
                    "page": page["page"],
                    "label": label,
                    "value_text": number_text.replace("，", ","),
                    "scope": scope,
                    "unit": _detect_unit(context, match.start()),
                    "confidence": confidence,
                    "excerpt": _excerpt(context, match.start(), match.end() + len(number_text)),
                })
        carry = (carry + text)[-30000:]
    units = [item["unit"] for item in candidates if item.get("unit")]
    if units:
        common = max(set(units), key=units.count)
        for item in candidates:
            if not item.get("unit"):
                item["unit"] = common
                item["confidence"] = max(0.0, item["confidence"] - 0.05)
    return candidates


def extract_annual_report(
    pdf_path: str | Path,
    *,
    company_id: str,
    fiscal_year: int,
    report_version: str = "",
    period_end: str = "",
) -> dict:
    path = Path(pdf_path)
    pages = read_pages(path)
    total_chars = sum(len(page["text"].strip()) for page in pages)
    warnings: list[str] = []
    if total_chars < 200:
        warnings.append("文本层为空或过短，疑似扫描件，需要 OCR 后再抽取")

    employee_candidates = find_employee_candidates(pages)
    asset_candidates = find_asset_candidates(pages)
    employee = max(employee_candidates, key=lambda item: item["confidence"], default=None)
    consolidated = [item for item in asset_candidates if item["scope"] == "consolidated"]
    # 同一口径下取金额最大的命中：资产总计是报表中的最大数字，可排除正文叙述里的
    # 近似值（例如“资产总额130,705.23亿元”这类行文）。
    def _asset_key(item: dict):
        try:
            amount = float(str(item["value_text"]).replace(",", ""))
        except (TypeError, ValueError):
            amount = 0.0
        return (item["confidence"], amount)

    asset = max(consolidated or asset_candidates, key=_asset_key, default=None)

    if employee is None:
        warnings.append("未找到员工人数候选（合计类关键词缺失）")
    if asset is None:
        warnings.append("未找到资产总计候选")
    elif consolidated and len(asset_candidates) > len(consolidated):
        warnings.append("资产总计存在合并与母公司多个口径，已取合并口径，请人工复核")
    if asset is not None and not asset.get("unit"):
        warnings.append("未识别到金额单位，请人工确认后再入库")
    elif asset is not None and asset.get("unit") != "元":
        warnings.append(f"报表单位为“{asset['unit']}”，已自动换算为元，请复核")

    evidence = []
    if employee is not None:
        evidence.append({
            "field_name": "employee_count",
            "source_type": "annual_report",
            "source_page": str(employee["page"]),
            "source_excerpt": employee["excerpt"],
            "extraction_method": "pymupdf-text",
            "extraction_confidence": employee["confidence"],
        })
    if asset is not None:
        evidence.append({
            "field_name": "total_assets",
            "source_type": "annual_report",
            "source_page": str(asset["page"]),
            "source_excerpt": asset["excerpt"],
            "extraction_method": "pymupdf-text",
            "extraction_confidence": asset["confidence"],
        })

    return {
        "company_id": company_id,
        "fiscal_year": int(fiscal_year),
        "reporting_scope": "consolidated",
        "report_version": report_version or f"annual-{fiscal_year}",
        "period_end": period_end,
        "employee_count": employee["value"] if employee else None,
        "employee_count_type": "year_end",
        "employee_count_scope": "consolidated",
        "total_assets": _convert_to_yuan(asset["value_text"], asset.get("unit")) if asset else None,
        "currency": "CNY",
        "unit_original": asset.get("unit") if asset else None,
        "total_assets_scope": asset.get("scope") if asset else None,
        "evidence": evidence,
        "_extraction": {
            "pdf": str(path),
            "pages": len(pages),
            "text_chars": total_chars,
            "employee_candidates": employee_candidates,
            "asset_candidates": asset_candidates,
            "total_assets_raw_text": asset["value_text"] if asset else None,
            "warnings": warnings,
            "needs_review": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="年报 PDF 抽取（候选，需人工复核）")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--fiscal-year", type=int, required=True)
    parser.add_argument("--report-version", default="")
    parser.add_argument("--period-end", default="")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    payload = extract_annual_report(
        args.pdf, company_id=args.company_id, fiscal_year=args.fiscal_year,
        report_version=args.report_version, period_end=args.period_end,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary = {
            "output": args.output,
            "employee_count": payload["employee_count"],
            "total_assets": payload["total_assets"],
            "unit_original": payload["unit_original"],
            "warnings": payload["_extraction"]["warnings"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
