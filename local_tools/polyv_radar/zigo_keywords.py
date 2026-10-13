"""Build a versioned, source-traceable ZigoAI keyword registry."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .zigo_store import ZigoStore

TAXONOMY_PATH = Path(__file__).with_name("zigo_taxonomy.json")
PRODUCTS = ("sales_agent", "geo")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def _source_match(keyword: str, chunks: list[dict], product: str) -> tuple[str, list[int]]:
    needle = _norm(keyword)
    matches = [row for row in chunks if row.get("domain") == product and needle and needle in _norm(row.get("text", ""))]
    if not matches:
        return "", []
    return str(matches[0].get("source_id") or ""), sorted({int(row.get("page", 0)) for row in matches if row.get("page")})


def _source_match_terms(terms: list[str], chunks: list[dict], product: str) -> tuple[str, list[int]]:
    """Attach the first material evidence for a composite practical query."""
    for term in terms:
        source_id, pages = _source_match(str(term), chunks, product)
        if source_id:
            return source_id, pages
    return "", []


def build_keyword_registry(knowledge_root: Path, output: Path, taxonomy_path: Path = TAXONOMY_PATH) -> dict:
    knowledge_root = Path(knowledge_root)
    if not (knowledge_root / "manifest.json").is_file() and (knowledge_root / "knowledge").is_dir():
        knowledge_root = knowledge_root / "knowledge"
    manifest_path = knowledge_root / "manifest.json"
    chunks_path = knowledge_root / "chunks.jsonl"
    manifest_bytes = manifest_path.read_bytes()
    chunks_bytes = chunks_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    chunks = [json.loads(line) for line in chunks_bytes.decode("utf-8").splitlines() if line.strip()]
    taxonomy_path = Path(taxonomy_path)
    taxonomy_bytes = taxonomy_path.read_bytes()
    taxonomy = json.loads(taxonomy_bytes.decode("utf-8"))
    source_hash = hashlib.sha256(manifest_bytes + chunks_bytes).hexdigest()
    taxonomy_hash = hashlib.sha256(taxonomy_bytes).hexdigest()
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    manifest_by_id = {str(doc.get("source_id")): doc for doc in manifest.get("documents", [])}
    for product in PRODUCTS:
        rules = taxonomy[product]
        categories = {
            "discovery": rules.get("search_terms", []),
            "query": rules.get("queries", []),
            "practice_scenario": rules.get("practice_scenarios", []),
            "buyer_demand": rules.get("buyer_demand_terms", []),
            "purchase_intent": rules.get("purchase_intent_terms", []),
            "buyer_signal": [term for terms in rules.get("signals", {}).values() for term in terms],
            "comment": rules.get("comment_keywords", []),
            "tag": rules.get("tags", []),
        }
        for category, values in categories.items():
            for keyword in values:
                keyword = str(keyword).strip()
                key = (product, category, _norm(keyword))
                if not keyword or key in seen:
                    continue
                seen.add(key)
                source_id, pages = _source_match(keyword, chunks, product)
                source_doc = manifest_by_id.get(source_id, {})
                rows.append({
                    "product_domain": product,
                    "keyword": keyword,
                    "category": category,
                    "derivation": "material_excerpt" if source_id else "curated_search_term",
                    "source_id": source_id,
                    "source_file": str(source_doc.get("file_name") or ""),
                    "source_pages": pages,
                    "source_sha256": source_hash,
                })
        for expansion in rules.get("query_expansions", []):
            if isinstance(expansion, str):
                expansion = {"keyword": expansion}
            keyword = str(expansion.get("keyword") or "").strip()
            key = (product, "query", _norm(keyword))
            if not keyword or key in seen:
                continue
            seen.add(key)
            source_terms = [str(term).strip() for term in expansion.get("source_terms", []) if str(term).strip()]
            source_id, pages = _source_match_terms(source_terms or [keyword], chunks, product)
            source_doc = manifest_by_id.get(source_id, {})
            rows.append({
                "product_domain": product,
                "keyword": keyword,
                "category": "query",
                "query_kind": str(expansion.get("query_kind") or "practice_buyer_query"),
                "scenario": str(expansion.get("scenario") or ""),
                "source_terms": source_terms,
                "derivation": "material_backed_query" if source_id else "curated_search_hypothesis",
                "source_id": source_id,
                "source_file": str(source_doc.get("file_name") or ""),
                "source_pages": pages,
                "source_sha256": source_hash,
            })
    version = f"zigo-material-{source_hash[:12]}-tax-{taxonomy_hash[:8]}"
    for row in rows:
        row["version"] = version
    payload = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_root": str(knowledge_root),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "chunks_sha256": hashlib.sha256(chunks_bytes).hexdigest(),
        "taxonomy_sha256": taxonomy_hash,
        "documents": manifest.get("documents", []),
        "keywords": rows,
        "query_registry": [row for row in rows if row["category"] == "query"],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"version": version, "keyword_count": len(rows), "output": str(output), "source_sha256": source_hash}


def load_keyword_registry(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def persist_keyword_registry(registry: dict, db_path: Path) -> dict:
    store = ZigoStore(db_path)
    store.initialize()
    rows = registry.get("keywords", [])
    store.ingest_run("__keyword_registry__", "sales_agent", [], [], keyword_sources=rows)
    store.close()
    return {"version": registry.get("version", ""), "persisted": len(rows), "db": str(db_path)}
