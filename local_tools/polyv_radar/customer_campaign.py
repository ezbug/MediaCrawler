"""Evidence-gated POLYV organization campaigns on an existing RadarStore.

Call initialize_campaign once before using a campaign. All mutations commit via
the store's connection, like RadarStore. No discovery, sending, or remote IO is
performed. Payloads and their revisions are retained as JSON evidence.

Company identity: company_id, official_domain, official_organization_id (optionally
organization_id_authority). Qualification: identity_status='verified', an official
identity, company_name, business_type, scenario, source_url, quote,
source_verified=True, contact_entry_url and fit_reason. Scores default to zero.

Outreach: source_url, quote, actual_date, own_account_id, other_account_id,
submitted=True, verified=True, own_account=True, target_relation=True.
Exchange: company_id, source_url, actual_date, own_account_id, other_account_id,
other_quote, own_quote (our follow-up), source_verified=True,
target_relation=True, substantive_business_response=True. Incomplete evidence
is retained but never counted. Flags must be JSON booleans, not truthy strings.
One account pair / source URL / platform / calendar day is one event per type;
quote edits, follow-up revisions and caller-supplied event IDs do not multiply it.
Contact/reply/exchange totals only include currently qualified organizations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from .storage import RadarStore


_FIELDS = (
    "company_name", "business_type", "scenario", "source_url", "quote",
    "published_at", "contact_entry_url", "fit_reason", "identity_status",
    "reply_text", "next_action", "official_domain", "official_organization_id",
    "organization_id_authority", "active_status", "demand_age_days",
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _key(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _url(value: object) -> bool:
    try:
        parsed = urlsplit(_text(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


def _brand(payload: dict) -> None:
    for name in ("brand", "campaign_brand", "product_brand"):
        if name in payload and _text(payload[name]).upper() != "POLYV":
            raise ValueError("Campaign brand must be POLYV")


def _campaign(store: RadarStore, campaign_id: str) -> dict:
    row = store.connection.execute(
        "SELECT * FROM polyv_customer_campaigns WHERE campaign_id=?", (campaign_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Unknown campaign; call initialize_campaign first")
    if row["brand"] != "POLYV":
        raise ValueError("Campaign brand must be POLYV")
    return dict(row)


def initialize_campaign(
    store: RadarStore, campaign_id: str, sector: str,
    target_companies: int = 100, target_exchanges: int = 2,
) -> dict:
    """Add campaign tables without changing legacy tables or campaign settings.

    Repeated calls are idempotent; conflicting settings raise ValueError.
    Returns campaign_id, brand, sector and both targets.
    """
    campaign_id, sector = _text(campaign_id), _text(sector)
    if not campaign_id or "zigo" in campaign_id.lower() or not sector:
        raise ValueError("A POLYV campaign_id and sector are required")
    for target in (target_companies, target_exchanges):
        if type(target) is not int or target < 0:
            raise ValueError("Targets must be nonnegative integers")
    store.initialize()
    store.connection.executescript("""
        CREATE TABLE IF NOT EXISTS polyv_customer_campaigns (
            campaign_id TEXT PRIMARY KEY, brand TEXT NOT NULL CHECK(brand='POLYV'),
            sector TEXT NOT NULL, target_companies INTEGER NOT NULL,
            target_exchanges INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS polyv_campaign_companies (
            campaign_id TEXT NOT NULL, company_id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(campaign_id, company_id)
        );
        CREATE TABLE IF NOT EXISTS polyv_campaign_identities (
            campaign_id TEXT NOT NULL, identity_key TEXT NOT NULL, company_id TEXT NOT NULL,
            PRIMARY KEY(campaign_id, identity_key)
        );
        CREATE TABLE IF NOT EXISTS polyv_campaign_history (
            campaign_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            revision_key TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL,
            PRIMARY KEY(campaign_id, entity_type, entity_id, revision_key)
        );
        CREATE TABLE IF NOT EXISTS polyv_campaign_events (
            campaign_id TEXT NOT NULL, company_id TEXT NOT NULL, event_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT NOT NULL,
            interaction_id INTEGER NOT NULL,
            PRIMARY KEY(campaign_id, event_id)
        );
        CREATE INDEX IF NOT EXISTS polyv_campaign_events_company
            ON polyv_campaign_events(campaign_id, company_id);
    """)
    expected = dict(campaign_id=campaign_id, brand="POLYV", sector=sector,
                    target_companies=target_companies, target_exchanges=target_exchanges)
    with store.connection:
        store.connection.execute(
            "INSERT OR IGNORE INTO polyv_customer_campaigns VALUES (?, 'POLYV', ?, ?, ?)",
            (campaign_id, sector, target_companies, target_exchanges),
        )
        result = _campaign(store, campaign_id)
        if result != expected:
            raise ValueError("Existing campaign settings differ")
    return result


def _identities(payload: dict) -> list[str]:
    identities = []
    official_id = _text(payload.get("official_organization_id"))
    if official_id:
        authority = _text(payload.get("organization_id_authority"))
        identities.append("organization:" + _json([authority, official_id]))
    domain = _text(payload.get("official_domain"))
    if domain:
        parsed = urlsplit(domain if "://" in domain else "https://" + domain)
        if not _url(parsed.geturl()) or not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("official_domain must be an official hostname or HTTP URL")
        host = parsed.hostname.lower().rstrip(".").encode("idna").decode("ascii")
        if host.startswith("www."):
            host = host[4:]
        identities.append("domain:" + host)
    return identities


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Scores must be numeric in 0..10")
    if not math.isfinite(value) or not 0 <= value <= 10:
        raise ValueError("Scores must be numeric in 0..10")
    return value


def _company_state(payload: dict) -> tuple[str, list[str]]:
    if payload.get("business_type") == "video_competitor":
        return "excluded", ["video_competitor"]
    missing = [name for name in ("company_name", "business_type", "scenario", "quote", "fit_reason")
               if not _text(payload.get(name))]
    missing += [name for name in ("source_url", "contact_entry_url") if not _url(payload.get(name))]
    if payload.get("identity_status") != "verified" or not _identities(payload):
        missing.append("verified_organization_identity")
    if payload.get("source_verified") is not True:
        missing.append("source_verified")
    return ("pending" if missing else "qualified"), missing


def _history(store: RadarStore, campaign_id: str, kind: str, entity_id: str, payload: dict) -> None:
    store.connection.execute(
        "INSERT OR IGNORE INTO polyv_campaign_history VALUES (?, ?, ?, ?, ?, ?)",
        (campaign_id, kind, entity_id, _key(payload), _json(payload),
         datetime.now(timezone.utc).isoformat()),
    )


def upsert_company(store: RadarStore, campaign_id: str, payload: dict) -> dict:
    """Patch a company by exact official identity; reject conflicting identities.

    Explicit company_id permits pending records without official identity. Scores
    and independent active_status/demand_age_days are retained, never inferred
    from one another. Unknown fields (including accounts/content/outreach links)
    remain in evidence. Changed snapshots are retained in the history table.
    """
    _campaign(store, campaign_id)
    _brand(payload)
    if payload.get("campaign_id", campaign_id) != campaign_id:
        raise ValueError("Company campaign does not match")
    identities = _identities(payload)
    explicit_id = _text(payload.get("company_id"))
    if not identities and not explicit_id:
        raise ValueError("company_id or official organization identity required")
    with store.connection:
        matches = set()
        for identity in identities:
            row = store.connection.execute(
                "SELECT company_id FROM polyv_campaign_identities WHERE campaign_id=? AND identity_key=?",
                (campaign_id, identity),
            ).fetchone()
            if row:
                matches.add(row[0])
        if len(matches) > 1 or (matches and explicit_id and explicit_id not in matches):
            raise ValueError("Conflicting company identities")
        company_id = explicit_id or next(iter(matches), "org-" + _key(identities[0] if identities else ""))
        row = store.connection.execute(
            "SELECT payload FROM polyv_campaign_companies WHERE campaign_id=? AND company_id=?",
            (campaign_id, company_id),
        ).fetchone()
        old = json.loads(row[0]) if row else {}
        # Official identities can be enriched but not silently reassigned.
        for field in ("official_organization_id", "organization_id_authority", "official_domain"):
            if old.get(field) and field in payload and old[field] != payload[field]:
                if field != "official_domain" or _identities({field: old[field]}) != _identities({field: payload[field]}):
                    raise ValueError("Existing official identity cannot be reassigned")
        result = {name: "" for name in _FIELDS}
        result.update(fit_score=0, intent_score=0, source_verified=False,
                      active_status="unknown", demand_age_days=None, evidence={})
        result.update(old)
        result.update({name: payload[name] for name in (*_FIELDS, "fit_score", "intent_score", "source_verified")
                       if name in payload})
        result["company_id"] = company_id
        result["campaign_id"] = campaign_id
        result["brand"] = "POLYV"
        result["fit_score"] = _score(result["fit_score"])
        result["intent_score"] = _score(result["intent_score"])
        age = result["demand_age_days"]
        if age is not None and (type(age) is not int or age < 0):
            raise ValueError("demand_age_days must be a nonnegative integer or None")
        evidence = payload.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be a dictionary")
        result["evidence"] = {**result["evidence"], **evidence}
        result["evidence"].update({k: v for k, v in payload.items() if k not in result and k != "evidence"})
        if "status" in payload:
            result["evidence"]["requested_status"] = payload["status"]
        result["status"], result["missing_evidence"] = _company_state(result)
        for identity in _identities(result):
            store.connection.execute("INSERT OR IGNORE INTO polyv_campaign_identities VALUES (?, ?, ?)",
                                     (campaign_id, identity, company_id))
        store.connection.execute(
            "INSERT INTO polyv_campaign_companies VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id,company_id) DO UPDATE SET payload=excluded.payload",
            (campaign_id, company_id, _json(result)),
        )
        _history(store, campaign_id, "company", company_id, result)
    return result


def list_companies(store: RadarStore, campaign_id: str) -> list[dict]:
    _campaign(store, campaign_id)
    return [json.loads(row[0]) for row in store.connection.execute(
        "SELECT payload FROM polyv_campaign_companies WHERE campaign_id=? ORDER BY company_id", (campaign_id,)
    )]


def _actual_date(value: object) -> bool:
    try:
        text = _text(value)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return bool(text) and parsed.date() <= date.today()
    except ValueError:
        return False


def _substantive(value: object) -> bool:
    text = re.sub(r"[\W_]+", "", _text(value).casefold())
    # Courtesy-only replies remain evidence, but do not constitute business exchanges.
    courtesy = r"(?:thanks|thankyou|thankssomuch|thankyouverymuch|forsharing|foryourreply|forthereply|" \
               r"ok|okay|great|yes|gotit|\u8c22\u8c22|\u611f\u8c22|\u591a\u8c22|\u597d\u7684|\u597d|\u6536\u5230|\u660e\u767d|" \
               r"\u5206\u4eab|\u56de\u590d|\u652f\u6301|\u8001\u5e08|\u7684|\u60a8|\u4f60)+"
    return bool(text) and re.fullmatch(courtesy, text) is None


def _event_state(kind: str, payload: dict) -> tuple[bool, bool, list[str]]:
    missing = []
    for field in ("own_account_id", "other_account_id"):
        if not _text(payload.get(field)):
            missing.append(field)
    if payload.get("own_account_id") == payload.get("other_account_id"):
        missing.append("distinct_accounts")
    if not _url(payload.get("source_url")):
        missing.append("source_url")
    if not _actual_date(payload.get("actual_date")):
        missing.append("actual_date")
    flags = ("submitted", "verified", "own_account", "target_relation") if kind == "outreach" else (
        "source_verified", "target_relation")
    missing += [field for field in flags if payload.get(field) is not True]
    if kind == "outreach" and any(
        _text(payload.get(field)).lower() in {"dry_run", "dry-run", "draft", "preview", "failed"}
        for field in ("mode", "status")
    ):
        missing.append("actual_submission")
    quote_field = "quote" if kind == "outreach" else "other_quote"
    if not _text(payload.get(quote_field)):
        missing.append(quote_field)
    replied = kind == "exchange" and not missing
    if kind == "exchange":
        if payload.get("substantive_business_response") is not True or not _substantive(payload.get("other_quote")):
            missing.append("substantive_business_response")
        if not _substantive(payload.get("own_quote")):
            missing.append("our_follow_up")
    return not missing, replied, missing


def _record_event(store: RadarStore, campaign_id: str, company_id: str, kind: str, payload: dict) -> dict:
    _campaign(store, campaign_id)
    _brand(payload)
    if payload.get("campaign_id", campaign_id) != campaign_id or payload.get("company_id", company_id) != company_id:
        raise ValueError("Event campaign/company does not match")
    if not store.connection.execute(
        "SELECT 1 FROM polyv_campaign_companies WHERE campaign_id=? AND company_id=?", (campaign_id, company_id)
    ).fetchone():
        raise ValueError("Unknown campaign company")
    evidence = dict(payload)
    counted, replied, missing = _event_state(kind, evidence)
    # Caller IDs and changing verification flags cannot manufacture new events.
    actual_date = _text(evidence.get("actual_date"))
    if _actual_date(actual_date):
        actual_date = datetime.fromisoformat(actual_date.replace("Z", "+00:00")).date().isoformat()
    event_id = _key([company_id, kind, _text(evidence.get("platform")).lower(),
                     *[_text(evidence.get(k)) for k in ("source_url", "own_account_id", "other_account_id")],
                     actual_date])
    result = dict(campaign_id=campaign_id, company_id=company_id, brand="POLYV", event_id=event_id,
                  event_type=kind, status="verified" if counted else "pending", counted=counted,
                  replied=replied, missing_evidence=missing, evidence=evidence)
    with store.connection:
        previous = store.connection.execute(
            "SELECT interaction_id FROM polyv_campaign_events WHERE campaign_id=? AND event_id=?", (campaign_id, event_id)
        ).fetchone()
        values = ("campaign:" + campaign_id, _text(evidence.get("platform")),
                  _text(evidence.get("source_url")), _text(evidence.get("other_account_id")),
                  "campaign_" + kind, _text(evidence.get("other_quote", evidence.get("quote"))),
                  _text(evidence.get("actual_date")), result["status"], _json(result))
        if previous:
            interaction_id = previous[0]
            store.connection.execute(
                "UPDATE interaction_events SET run_id=?,platform=?,source_url=?,author=?,event_type=?,"
                "quote=?,observed_at=?,status=?,metadata=? WHERE interaction_id=?", (*values, interaction_id)
            )
        else:
            cursor = store.connection.execute(
                "INSERT INTO interaction_events (run_id,platform,source_url,author,event_type,quote,observed_at,status,metadata) "
                "VALUES (?,?,?,?,?,?,?,?,?)", values
            )
            interaction_id = cursor.lastrowid
        result["interaction_id"] = interaction_id
        store.connection.execute(
            "INSERT INTO polyv_campaign_events VALUES (?,?,?,?,?,?) ON CONFLICT(campaign_id,event_id) "
            "DO UPDATE SET payload=excluded.payload", (campaign_id, company_id, event_id, kind, _json(result), interaction_id)
        )
        _history(store, campaign_id, kind, event_id, result)
    return result


def link_outreach(store: RadarStore, campaign_id: str, company_id: str, payload: dict) -> dict:
    """Link submitted outreach evidence; dry-runs/incomplete attempts stay pending."""
    return _record_event(store, campaign_id, company_id, "outreach", payload)


def record_exchange(store: RadarStore, campaign_id: str, payload: dict) -> dict:
    """Record a two-party business response plus our follow-up (own_quote)."""
    return _record_event(store, campaign_id, _text(payload.get("company_id")), "exchange", payload)


def campaign_summary(store: RadarStore, campaign_id: str) -> dict:
    """Recompute the funnel from qualified organizations and verified evidence.

    Contact/reply counters count unique qualified companies. Exchanges count
    distinct evidenced conversations; none of these counters trust claimed
    company status, reply_text, fit/intent scores, or supplied summary counters.
    """
    campaign = _campaign(store, campaign_id)
    companies = list_companies(store, campaign_id)
    qualified = {c["company_id"] for c in companies if _company_state(c)[0] == "qualified"}
    contacted, replied, exchanges = set(), set(), set()
    for row in store.connection.execute(
        "SELECT * FROM polyv_campaign_events WHERE campaign_id=?", (campaign_id,)
    ):
        if row["company_id"] not in qualified:
            continue
        event = json.loads(row["payload"])
        valid, has_reply, _ = _event_state(row["event_type"], event["evidence"])
        if row["event_type"] == "outreach" and valid:
            contacted.add(row["company_id"])
        if has_reply:
            replied.add(row["company_id"])
        if row["event_type"] == "exchange" and valid:
            exchanges.add(row["event_id"])
    return {**campaign, "qualified_companies": len(qualified), "contacted_companies": len(contacted),
            "replied_companies": len(replied), "effective_exchanges": len(exchanges),
            "pending_companies": sum(_company_state(c)[0] == "pending" for c in companies)}
