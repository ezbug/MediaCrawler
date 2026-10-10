"""同行调查结构化提炼：价格情报表 + 宣传话术库（离线）。

读取 peer-research/raw 下的采集结果，产出两张结构化表：
- 价格情报表：带来源的价格金额、分成比例与计费术语。
- 宣传话术库：同行宣传内容分类 + 评论区触达话术（联系方式已遮蔽）。
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

PRICE_SUFFIX_PATTERN = re.compile(r"([0-9][0-9,，]*(?:\.[0-9]+)?)\s*(万元|万|元|块)")
COMMISSION_PATTERN = re.compile(r"抽成\s*([0-9]+(?:\.[0-9]+)?)\s*%")
PRICE_CONTEXT_TERMS = ("价格", "报价", "费用", "收费", "多少钱", "预算", "年费", "月费", "性价比", "套餐")
ROUNDUP_TERMS = ("对比", "排行", "盘点", "十大", "TOP", "Top", "top", "测评", "评测", "选型", "避坑", "哪个好", "怎么选")
QUESTION_TERMS = ("求推荐", "请问", "有没有", "推荐一下", "哪家", "?", "？")
VENDOR_AUTHOR_TERMS = ("直播", "软件", "评测", "办会", "科技", "网络", "云", "SaaS", "saas")
OUTREACH_TERMS = ("私信", "加我", "加微", "微信", "联系我", "免费试用", "咨询我", "了解详情", "领取", "优惠", "折扣", "备注")

PRICE_FIELDS = ("品牌", "平台", "类型", "价格信号", "原文片段", "标题", "链接", "作者", "发布时间", "查询", "批次")
PROMO_FIELDS = ("类型", "品牌", "提及品牌", "标题", "作者", "平台", "链接", "发布时间", "原文/摘要", "查询", "批次")


def mask_contacts(text: str) -> str:
    """遮蔽邮箱与长数字串，避免把联系方式写进报告。"""
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已遮蔽]", text)
    text = re.sub(r"(微信|VX|vx|V信|WX|wx)\s*[:：]?\s*[A-Za-z0-9_-]{4,}", r"\1[已遮蔽]", text)
    return re.sub(r"\d{5,}", "[数字已遮蔽]", text)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def load_plan_brand_map(peer_root: Path) -> dict[tuple[str, str], str]:
    """从各批次的 plan.json 读取 (平台, 查询) -> 品牌 映射。"""
    mapping: dict[tuple[str, str], str] = {}
    runs_root = Path(peer_root) / "runs"
    if not runs_root.exists():
        return mapping
    for plan_path in sorted(runs_root.glob("*/plan.json")):
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for query in plan.get("queries") or []:
            brand = query.get("brand")
            if brand:
                mapping[(str(query.get("platform") or ""), str(query.get("query") or ""))] = str(brand)
    return mapping


def _record_brand(row: dict, platform: str, query: str, brand_map: dict[tuple[str, str], str]) -> str:
    brand = brand_map.get((platform, query)) or ""
    if brand:
        return brand
    for field in ("title", "text", "author"):
        value = str(row.get(field) or "")
        for known in brand_map.values():
            if known in value:
                return known
    return ""


def load_peer_records(peer_root: Path, run_ids: list[str] | None = None) -> list[dict]:
    """读取 peer-research/raw 下的内容与评论记录。"""
    peer_root = Path(peer_root)
    raw_root = peer_root / "raw"
    brand_map = load_plan_brand_map(peer_root)
    selected = set(run_ids) if run_ids else None
    records: list[dict] = []
    if not raw_root.exists():
        return records
    for run_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        if selected and run_dir.name not in selected:
            continue
        for platform_dir in sorted(path for path in run_dir.iterdir() if path.is_dir()):
            platform = platform_dir.name
            for query_dir in sorted(path for path in platform_dir.iterdir() if path.is_dir()):
                query = re.sub(r"^\d+-", "", query_dir.name)
                content_index: dict[str, dict] = {}
                for row in _read_jsonl(query_dir / f"{platform}_contents.jsonl"):
                    content_id = str(row.get("content_id") or "")
                    record = {
                        "run_id": run_dir.name,
                        "platform": platform,
                        "query": query,
                        "record_type": "content",
                        "record_id": content_id,
                        "title": str(row.get("title") or ""),
                        "text": str(row.get("text") or ""),
                        "url": str(row.get("url") or ""),
                        "author": str(row.get("author") or ""),
                        "published": str(row.get("published_at_raw") or row.get("create_time") or ""),
                        "brand": _record_brand(row, platform, query, brand_map),
                        "likes": row.get("likes") or 0,
                    }
                    if content_id:
                        content_index[content_id] = record
                    records.append(record)
                for row in _read_jsonl(query_dir / f"{platform}_comments.jsonl"):
                    parent = content_index.get(str(row.get("content_id") or "")) or {}
                    records.append(
                        {
                            "run_id": run_dir.name,
                            "platform": platform,
                            "query": query,
                            "record_type": "comment",
                            "record_id": str(row.get("comment_id") or ""),
                            "title": str(parent.get("title") or ""),
                            "text": str(row.get("text") or ""),
                            "url": str(row.get("comment_url") or parent.get("url") or ""),
                            "author": str(row.get("author") or ""),
                            "published": str(row.get("published_at_raw") or row.get("create_time") or ""),
                            "brand": _record_brand(row, platform, query, brand_map),
                            "likes": row.get("likes") or 0,
                        }
                    )
    return records


def _context(text: str, start: int, end: int, radius: int = 40) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)].strip()


def extract_price_signals(records: list[dict]) -> list[dict]:
    """提取价格金额与分成比例信号，标注来源与上下文。"""
    signals: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(record: dict, price_text: str, signal_type: str, snippet: str) -> None:
        key = (record["run_id"], record["platform"], record["record_id"], price_text)
        if key in seen:
            return
        seen.add(key)
        signals.append(
            {
                "brand": record["brand"],
                "platform": record["platform"],
                "signal_type": signal_type,
                "price_text": price_text,
                "snippet": mask_contacts(snippet),
                "title": record["title"],
                "url": record["url"],
                "author": record["author"],
                "published": record["published"],
                "query": record["query"],
                "run_id": record["run_id"],
            }
        )

    for record in records:
        blob = " ".join(part for part in (record["title"], record["text"]) if part).strip()
        if not blob:
            continue
        for match in PRICE_SUFFIX_PATTERN.finditer(blob):
            suffix = match.group(2)
            if suffix == "万":
                # 裸“万”需要近距离价格语境，避免把“7万职工”这类规模数字当报价。
                snippet = _context(blob, match.start(), match.end(), radius=12)
            else:
                snippet = _context(blob, match.start(), match.end())
            if suffix == "万" and not any(term in snippet for term in PRICE_CONTEXT_TERMS):
                continue
            add(record, match.group(0).strip(), "报价金额", snippet)
        for match in COMMISSION_PATTERN.finditer(blob):
            add(record, match.group(0).strip(), "分成比例", _context(blob, match.start(), match.end()))
    return signals


def classify_promo(record: dict, brand_names: set[str]) -> str:
    author = record["author"]
    title = record["title"]
    if any(brand and brand in author for brand in brand_names):
        return "同行自家账号"
    if any(term in author for term in VENDOR_AUTHOR_TERMS):
        return "同行或媒体账号"
    if any(term in title for term in ROUNDUP_TERMS):
        return "测评或排行内容"
    if any(term in title for term in QUESTION_TERMS):
        return "用户讨论"
    return "其他"


def build_promo_rows(records: list[dict], brand_names: set[str]) -> list[dict]:
    """宣传内容分类 + 评论区触达话术。"""
    rows: list[dict] = []
    for record in records:
        if record["record_type"] == "content":
            blob = " ".join(part for part in (record["title"], record["text"]) if part)
            mentions = sorted(brand for brand in brand_names if brand and brand in blob)
            summary = mask_contacts(record["text"].strip())[:160]
            rows.append(
                {
                    "row_type": classify_promo(record, brand_names),
                    "brand": record["brand"],
                    "mentions": ",".join(mentions),
                    "title": record["title"],
                    "author": record["author"],
                    "platform": record["platform"],
                    "url": record["url"],
                    "published": record["published"],
                    "excerpt": summary,
                    "query": record["query"],
                    "run_id": record["run_id"],
                }
            )
            continue
        hits = [term for term in OUTREACH_TERMS if term in record["text"]]
        if not hits:
            continue
        rows.append(
            {
                "row_type": "评论区触达话术",
                "brand": record["brand"],
                "mentions": "",
                "title": record["title"],
                "author": record["author"],
                "platform": record["platform"],
                "url": record["url"],
                "published": record["published"],
                "excerpt": mask_contacts(record["text"].strip())[:200],
                "query": record["query"],
                "run_id": record["run_id"],
            }
        )
    return rows


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict], keys: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for row in rows:
            writer.writerow([row.get(key, "") for key in keys])


def _price_row(signal: dict) -> dict:
    return {
        "品牌": signal["brand"],
        "平台": signal["platform"],
        "类型": signal["signal_type"],
        "价格信号": signal["price_text"],
        "原文片段": signal["snippet"],
        "标题": signal["title"],
        "链接": signal["url"],
        "作者": signal["author"],
        "发布时间": signal["published"],
        "查询": signal["query"],
        "批次": signal["run_id"],
    }


def _promo_row(row: dict) -> dict:
    return {
        "类型": row["row_type"],
        "品牌": row["brand"],
        "提及品牌": row["mentions"],
        "标题": row["title"],
        "作者": row["author"],
        "平台": row["platform"],
        "链接": row["url"],
        "发布时间": row["published"],
        "原文/摘要": row["excerpt"],
        "查询": row["query"],
        "批次": row["run_id"],
    }


def build_peer_reports(peer_root: Path, *, output_dir: Path | None = None, run_ids: list[str] | None = None) -> dict:
    """生成价格情报表与宣传话术库（CSV + Markdown）。"""
    from .peer_research import load_peer_taxonomy

    peer_root = Path(peer_root)
    records = load_peer_records(peer_root, run_ids)
    taxonomy = load_peer_taxonomy(Path(__file__).with_name("peer_research_taxonomy.json"))
    brand_names = {str(item["brand"]) for item in taxonomy["competitors"]}
    signals = extract_price_signals(records)
    promo_rows = build_promo_rows(records, brand_names)
    target_dir = Path(output_dir) if output_dir else peer_root / "reports"
    target_dir.mkdir(parents=True, exist_ok=True)

    price_csv = target_dir / "price-intel.csv"
    price_md = target_dir / "price-intel.md"
    promo_csv = target_dir / "promo-library.csv"
    promo_md = target_dir / "promo-library.md"
    price_rows = [_price_row(signal) for signal in signals]
    promo_table = [_promo_row(row) for row in promo_rows]
    _write_csv(price_csv, PRICE_FIELDS, price_rows, PRICE_FIELDS)
    _write_csv(promo_csv, PROMO_FIELDS, promo_table, PROMO_FIELDS)

    price_lines = [
        "# 同行价格情报表",
        "",
        f"- 记录数：{len(price_rows)}",
        f"- 覆盖批次：{', '.join(sorted({signal['run_id'] for signal in signals})) or '-'}",
        "",
        "| 品牌 | 平台 | 类型 | 价格信号 | 原文片段 | 作者 | 链接 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in price_rows[:60]:
        price_lines.append(
            f"| {row['品牌'] or '-'} | {row['平台']} | {row['类型']} | {row['价格信号']} | {row['原文片段'][:80]} | {row['作者']} | [来源]({row['链接']}) |"
        )
    price_md.write_text("\n".join(price_lines).rstrip() + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for row in promo_table:
        counts[row["类型"]] = counts.get(row["类型"], 0) + 1
    promo_lines = [
        "# 同行宣传与触达话术库",
        "",
        "- 分类统计：" + ("、".join(f"{key} {value}" for key, value in sorted(counts.items())) or "-"),
        "",
        "| 类型 | 品牌 | 标题 | 作者 | 链接 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in promo_table[:80]:
        promo_lines.append(
            f"| {row['类型']} | {row['品牌'] or '-'} | {row['标题'][:60] or row['原文/摘要'][:60]} | {row['作者']} | [来源]({row['链接']}) |"
        )
    promo_md.write_text("\n".join(promo_lines).rstrip() + "\n", encoding="utf-8")

    return {
        "records": len(records),
        "price_signals": len(price_rows),
        "promo_rows": len(promo_table),
        "promo_counts": counts,
        "price_csv": str(price_csv),
        "price_markdown": str(price_md),
        "promo_csv": str(promo_csv),
        "promo_markdown": str(promo_md),
    }
