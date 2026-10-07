"""Read-only ZigoAI discovery on the existing Ego collectors; no dispatch path."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .adapters import parse_datetime
from .config import load_config
from .ego_crawl_all import run_ego_crawlers
from .zigo_store import ZigoStore

TAXONOMY_PATH = Path(__file__).with_name("zigo_taxonomy.json")
TAXONOMY = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def product_evidence(root: Path, product: str) -> dict:
    manifest_path, chunks_path = root / "knowledge/manifest.json", root / "knowledge/chunks.jsonl"
    manifest_bytes, chunks_bytes = manifest_path.read_bytes(), chunks_path.read_bytes()
    sources = {row['source_id'] for row in json.loads(manifest_bytes)['documents'] if row['domain'] == product}
    pages = [row for line in chunks_bytes.decode('utf-8').splitlines() if line.strip()
             for row in [json.loads(line)] if row['domain'] == product
             and row['source_id'] in sources and row['page'] in TAXONOMY[product]['product_evidence_pages']]
    if not pages:
        raise ValueError('No registered product evidence for ' + product)
    return {'product_domain':product, 'claim_scope':'资料原文口径，非外部核验或效果承诺',
            'manifest_path':str(manifest_path), 'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),
            'chunks_path':str(chunks_path), 'chunks_sha256':hashlib.sha256(chunks_bytes).hexdigest(), 'pages':pages}


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def screen_record(record: dict, product: str, now: datetime | None = None) -> dict:
    rules = TAXONOMY[product]
    now = now or datetime.now(timezone.utc)
    quote = str(record.get("text") or record.get("quote") or "").strip()
    text = normalized(quote)
    author = str(record.get("author") or "")
    # A post's own title may establish its plan; selection evidence must stay in its body.
    company_geo_selection = (
        product == 'geo' and record.get('source_type') == 'post'
        and re.search(r'(?:我们公司|我司|公司)(?:想做|准备做|打算做)geo', normalized(record.get('title', '')))
        and re.search(r'想了解.{0,12}(?:价格|报价|效果)', text)
        and re.search(r'(?:合适|合适的话)(?:可|可以)合作', text)
    )
    signals = {name: [term for term in terms if normalized(term) in text]
               for name, terms in rules["signals"].items()}
    signals = {name: terms for name, terms in signals.items() if terms}
    if product == 'sales_agent' and '客户' in text and re.search(r'我|我们', text):
        acquisition = re.search(r'没开发出.{0,5}客户|自主开发.{0,25}难开发', text)
        if acquisition:
            signals.setdefault('execution_gap', []).append(acquisition.group())
    # An isolated plan expression is one signal, not two independent dimensions.
    if product == 'geo' and signals.get('purchase_intent') == ['想做'] and any(
        normalized(term) in text for term in ('想做GEO', '准备做GEO', '打算做GEO')
    ):
        signals.pop('purchase_intent')
    # Existing collectors write capture time into create_time. Never infer a public date from it.
    published = parse_datetime(record.get("published_at"))
    age = (now - published).total_seconds() / 86400 if published else None
    freshness = "unknown" if age is None else "future" if age < -1 else "current" if age <= 90 else "historical" if age <= 730 else "stale"
    reasons = []
    if record.get('platform_ai_agent') is True:
        reasons.append('platform_ai_agent_not_prospect')
    if not quote:
        reasons.append("empty_quote")
    if any(normalized(term) in normalized(author) for term in TAXONOMY["excluded_authors"]):
        reasons.append("own_or_product_account")
    negatives = [term for term in TAXONOMY["negative_patterns"] if normalized(term) in text]
    if negatives:
        reasons.append("provider_or_noise:" + ",".join(negatives))
    if len(signals) < 2:
        reasons.append("fewer_than_two_signal_types")
    if product == "sales_agent" and "execution_gap" not in signals and not re.search(r"跟进|接待|探需|成交|唤醒|回扫|转化|意向", text):
        reasons.append("no_sales_execution_need")
    if product == "geo" and not any(normalized(term) in text for term in rules["search_terms"]):
        reasons.append("no_ai_search_or_recommendation_need")
    if not company_geo_selection and not re.search(r"我|我们|公司|求|请问|怎么|有没有|能不能|一直|每天|太多|不过来|跟不上|不回|想做|准备做|打算做", text):
        reasons.append("no_personal_need_expression")
    if record.get("source_type") in {"post", "answer"}:
        if not company_geo_selection and not re.search(r"我们|我司|我公司|我在|我做|我的|求助|求推荐|有没有", text):
            reasons.append("publisher_is_not_established_buyer")
        if any(term in text for term in ("教程", "攻略", "盘点", "干货", "指南")) or re.search(
            r"(?:整理|分享|教你|教大家).{0,12}(?:话术|技巧|策略)|破冰(?:三|3|两|2)句话|(?:三|3|两|2)句(?:话|破冰)|话术[:：]|错误应对|核心心法", text
        ):
            reasons.append("guide_content")
    if freshness in {"stale", "future"}:
        reasons.append("publication_date_" + freshness)
    identity = record.get("author_id") or record.get("author_url") or ""
    target_key = [record.get("platform"), record.get("content_id"), identity or author,
                  record.get("native_comment_id") or normalized(quote), record.get("source_type")]
    candidate_id = hashlib.sha256(json.dumps([product, *target_key], ensure_ascii=False).encode()).hexdigest()[:20]
    status = "excluded" if reasons else "evidence_pending" if not published or not author else "candidate_pending_verification"
    return {**record, "candidate_id": candidate_id, "product_domain": product, "quote": quote,
            "signals": signals, "rule_score": len(signals) * 2, "decision": status,
            "exclusion_reasons": reasons, "freshness": freshness,
            "published_at": published.isoformat() if published else "", "identity_confidence": "low",
            "decision_role": "unknown", "priority": "P1" if "purchase_intent" in signals else "P2",
            "product_source_id": rules["product_source_id"],
            "product_evidence_pages": rules["product_evidence_pages"],
            "claim_scope": "资料原文口径，非效果承诺", "outreach_allowed": False}


def select_verified(records: list[dict], checks: list[dict]) -> list[dict]:
    checked = {item.get("candidate_id"): item for item in checks}
    selected, identities = [], set()
    for record in records:
        check = checked.get(record["candidate_id"], {})
        if record["decision"] != "candidate_pending_verification" or check.get("status") != "verified":
            continue
        if not check.get("container_verified") or not check.get("buyer_review_passed") or not check.get("verified_at"):
            continue
        if normalized(check.get("matched_author", "")) != normalized(record.get("author", "")):
            continue
        if normalized(check.get("matched_quote", "")) != normalized(record["quote"]):
            continue
        if check.get("content_id") != record.get("content_id") or check.get("platform") != record.get("platform"):
            continue
        identity = record.get("author_id") or record.get("author_url")
        if not identity:
            continue
        evidence = Path(check.get("evidence_path", ""))
        if not evidence.is_file():
            continue
        payload = evidence.read_bytes()
        if hashlib.sha256(payload).hexdigest() != check.get("evidence_sha256"):
            continue
        body = normalized(payload.decode("utf-8", errors="replace"))
        if normalized(record["quote"]) not in body or normalized(record["author"]) not in body:
            continue
        key = (record["product_domain"], record["platform"], identity)
        if key in identities:
            continue
        identities.add(key)
        selected.append({**record, "decision": "evidence_verified_candidate", "verification": check})
    return selected


def read_raw(raw_root: Path) -> list[dict]:
    contents, comments = {}, []
    for file in sorted(raw_root.rglob("*.jsonl")):
        for line_number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            raw["raw_source"] = f"{file}:{line_number}"
            if "comment" in file.name:
                comments.append(raw)
            else:
                contents[(raw["platform"], str(raw["content_id"]))] = raw
    rows = []
    for raw in comments:
        content = contents.get((raw["platform"], str(raw["content_id"])), {})
        rows.append({**raw, "url": content.get("url", ""), "content_title": content.get("title", ""),
                     "source_type": raw.get("source_type", "comment")})
    for content in contents.values():
        rows.append({**content, "source_type": "answer" if "/answer/" in content.get("url", "") else "post"})
    return rows


def export_report(output: Path, rows: list[dict], checks: list[dict], target: int = 10) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    unique = {row["candidate_id"]: row for row in rows}
    rows = list(unique.values())
    verified = select_verified(rows, checks)[:target]
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "target": target,
               "reviewed_records": len(rows), "decisions": dict(Counter(r["decision"] for r in rows)),
               "verified_candidates": len(verified), "gap": max(0, target - len(verified)), "sent": 0,
               "by_product": dict(Counter(r["product_domain"] for r in verified)),
               "exclusion_reasons": dict(Counter(reason for row in rows for reason in row["exclusion_reasons"]))}
    for product in ("sales_agent", "geo"):
        pool = [row for row in rows if row["product_domain"] == product]
        (output / f"{product}-screened.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pool), encoding="utf-8")
    (output / "verified-candidates.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in verified), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shown = verified + [r for r in rows if r["decision"] != "excluded" and r["candidate_id"] not in {v["candidate_id"] for v in verified}]
    def source_link(url):
        parsed = urlsplit(str(url))
        escaped = html.escape(str(url), quote=True)
        if parsed.scheme not in {'https', 'http'}:
            return escaped
        return f'<a href="{escaped}" rel="noopener noreferrer">原文</a>'
    table = "".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
        r["product_domain"], r["platform"], r.get("author"), r["quote"], r["published_at"] or "未知",
        r["decision"])) + '<td>' + source_link(r.get('url','')) + '</td></tr>' for r in shown)
    page = '<!doctype html><meta charset="utf-8"><title>ZigoAI 候选证据表</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left;overflow-wrap:anywhere}td{max-width:400px}</style>'
    page += f'<h1>ZigoAI 候选证据表</h1><p>核验 {len(verified)}/{target}；发送 0。规则初筛和证据待补不计入核验数量。</p>'
    page += '<table><thead><tr><th>产品</th><th>平台</th><th>作者</th><th>原话</th><th>时间</th><th>状态</th><th>来源URL</th></tr></thead><tbody>' + table + '</tbody></table>'
    (output / "candidates.html").write_text(page, encoding="utf-8")
    return summary


def load_registry_queries(
    registry_path: Path,
    product: str,
    limit: int | None = None,
    query_kinds: list[str] | None = None,
) -> tuple[list[str], list[dict], str]:
    """Load product-scoped query terms and provenance from the material registry."""
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    rows = [
        row for row in registry.get("query_registry", registry.get("keywords", []))
        if row.get("product_domain") == product and row.get("category", "query") == "query"
    ]
    if query_kinds:
        allowed = {str(kind).strip() for kind in query_kinds if str(kind).strip()}
        rows = [row for row in rows if str(row.get("query_kind") or "base") in allowed]
    if limit is not None:
        rows = rows[: max(0, limit)]
    queries = [str(row.get("keyword") or "").strip() for row in rows if str(row.get("keyword") or "").strip()]
    return queries, rows, str(registry.get("version") or "")


def run_discovery(
    config_path: Path,
    product: str,
    run_id: str,
    *,
    taskspace: int | None = None,
    platforms: list[str] | None = None,
    keywords: list[str] | None = None,
    collect: bool = False,
    checks_path: Path | None = None,
    keyword_registry: Path | None = None,
    product_root: Path = Path('/Volumes/GameSSD-Dev/CodexProjects/home/Users/sexpistole111/Documents/GOODS/ZIgoAI'),
    query_limit: int | None = None,
    query_kinds: list[str] | None = None,
    target: int = 10,
) -> dict:
    """Run one product-scoped, read-only ZigoAI discovery batch."""
    if product not in TAXONOMY:
        raise ValueError(f"unsupported ZigoAI product: {product}")
    if not re.fullmatch(r"[\w-]+", run_id):
        raise ValueError("run-id must be a simple name")

    config = load_config(Path(config_path))
    if config.product_profile != TAXONOMY[product]["profile"]:
        raise ValueError("config profile and requested product must match")
    if platforms:
        config = replace(config, platforms=platforms)

    registry_rows: list[dict] = []
    registry_version = ""
    if keywords:
        selected_queries = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    elif keyword_registry:
        selected_queries, registry_rows, registry_version = load_registry_queries(
            keyword_registry, product, query_limit, query_kinds
        )
    else:
        selected_queries = list(config.keywords.values())
        if query_limit is not None:
            selected_queries = selected_queries[: max(0, query_limit)]
    if selected_queries:
        config = replace(
            config,
            keywords={f"zigo_query_{index:03d}": query for index, query in enumerate(selected_queries, 1)},
            platform_keywords={},
            taxonomy_enabled=False,
        )

    evidence = product_evidence(Path(product_root), product)
    output = config.data_root / "reports" / run_id
    output.mkdir(parents=True, exist_ok=True)
    (output / "product-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "query-plan.json").write_text(json.dumps({
        "run_id": run_id,
        "product_domain": product,
        "registry_path": str(keyword_registry) if keyword_registry else "",
        "registry_version": registry_version,
        "query_kinds": query_kinds or [],
        "queries": selected_queries,
        "query_sources": registry_rows,
        "platforms": config.platforms,
        "collector": "ego",
        "outreach_allowed": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if collect:
        if not isinstance(taskspace, int) or taskspace <= 0:
            raise ValueError("collect requires an explicit logged-in Ego Lite taskspace")
        run_ego_crawlers(
            run_id,
            config.platforms,
            config,
            Path(__file__).resolve().parents[2],
            config.data_root,
            taskspace,
        )

    raw_root = config.data_root / "raw" / run_id
    raw_records = read_raw(raw_root) if raw_root.is_dir() else []
    records = [screen_record(row, product) for row in raw_records]
    checks = json.loads(Path(checks_path).read_text(encoding="utf-8")) if checks_path else []
    summary = export_report(output, records, checks, target=target)
    zigo_db = config.data_root.parent / "radar.sqlite3"
    store = ZigoStore(zigo_db)
    ingest = store.ingest_run(run_id, product, raw_records, records, checks, registry_rows)
    store.close()
    summary["zigo_db"] = str(zigo_db)
    summary["query_plan"] = str(output / "query-plan.json")
    summary["ingest"] = ingest
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--product", choices=["sales_agent", "geo"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--taskspace", type=int)
    parser.add_argument("--platform", action="append", choices=["xhs", "dy", "bili", "zhihu"])
    parser.add_argument("--keyword", action="append")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--keyword-registry", type=Path, help="已生成的资料来源关键词注册表")
    parser.add_argument("--query-limit", type=int, help="未指定 --keyword 时，从产品资料词库取前 N 条 query")
    parser.add_argument("--target", type=int, default=10)
    parser.add_argument("--product-root", type=Path, default=Path('/Volumes/GameSSD-Dev/CodexProjects/home/Users/sexpistole111/Documents/GOODS/ZIgoAI'))
    args = parser.parse_args()
    try:
        summary = run_discovery(
            args.config,
            args.product,
            args.run_id,
            taskspace=args.taskspace,
            platforms=args.platform,
            keywords=args.keyword,
            collect=args.collect,
            checks_path=args.checks,
            keyword_registry=args.keyword_registry,
            product_root=args.product_root,
            query_limit=args.query_limit,
            target=args.target,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
