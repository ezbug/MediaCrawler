from __future__ import annotations

import json

import pytest

from local_tools.polyv_radar.customer_campaign import (
    campaign_summary,
    initialize_campaign,
    link_outreach,
    list_companies,
    record_exchange,
    upsert_company,
)
from local_tools.polyv_radar.storage import RadarStore


@pytest.fixture
def store(tmp_path):
    value = RadarStore(tmp_path / "campaign.sqlite3")
    initialize_campaign(value, "national-day", "enterprise")
    yield value
    value.close()


def company(**changes):
    return {
        "company_name": "Acme Training", "business_type": "training_provider",
        "official_domain": "https://www.acme.example/about", "identity_status": "verified",
        "scenario": "Employee training", "source_url": "https://acme.example/project",
        "quote": "We need live employee training and playback.", "source_verified": True,
        "published_at": "2026-09-30", "contact_entry_url": "https://acme.example/contact",
        "fit_reason": "Live training and access controls", "fit_score": 8, "intent_score": 2,
        "active_status": "active", "demand_age_days": 3,
        "evidence": {"accounts": [{"platform": "xhs", "account_id": "buyer"}],
                     "content": [{"platform": "xhs", "content_id": "post"}]},
        **changes,
    }


def outreach(**changes):
    return {
        "platform": "xhs", "source_url": "https://social.example/thread/1",
        "quote": "We can discuss employee training requirements.", "actual_date": "2026-10-01",
        "own_account_id": "our-account", "other_account_id": "buyer",
        "submitted": True, "verified": True, "own_account": True, "target_relation": True,
        **changes,
    }


def exchange(company_id, **changes):
    return {
        "company_id": company_id, "platform": "xhs", "source_url": "https://social.example/thread/1",
        "actual_date": "2026-10-01", "own_account_id": "our-account", "other_account_id": "buyer",
        "other_quote": "Can your platform support 3000 staff and private playback?",
        "own_quote": "Yes. How many concurrent viewers and what access controls do you need?",
        "source_verified": True, "target_relation": True, "substantive_business_response": True,
        **changes,
    }


def count(store, table):
    return store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_incremental_migration_preserves_existing_records(tmp_path):
    legacy = RadarStore(tmp_path / "legacy.sqlite3")
    legacy.initialize()
    legacy.connection.execute("INSERT INTO leads VALUES ('legacy','xhs','post','','{}')")
    legacy.save_interaction_event({"run_id": "legacy", "quote": "Original evidence"})
    before = [tuple(r) for r in legacy.connection.execute("SELECT * FROM interaction_events")]
    schema = list(legacy.connection.execute("PRAGMA table_info(interaction_events)"))
    initialize_campaign(legacy, "national-day", "enterprise")
    initialize_campaign(legacy, "national-day", "enterprise")
    assert legacy.count("leads") == 1
    assert before == [tuple(r) for r in legacy.connection.execute("SELECT * FROM interaction_events")]
    assert [tuple(r) for r in schema] == [tuple(r) for r in legacy.connection.execute("PRAGMA table_info(interaction_events)")]
    assert count(legacy, "polyv_customer_campaigns") == 1
    with pytest.raises(ValueError, match="settings differ"):
        initialize_campaign(legacy, "national-day", "enterprise", target_companies=200)
    legacy.close()


def test_official_identity_dedup_history_and_explicit_fields(store):
    first = upsert_company(store, "national-day", company())
    replay = upsert_company(store, "national-day", company())
    assert replay == first
    assert first["status"] == "qualified"  # Training providers are eligible.
    assert first["fit_score"] == 8 and first["intent_score"] == 2
    assert first["active_status"] == "active" and first["demand_age_days"] == 3
    assert first["evidence"]["accounts"][0]["account_id"] == "buyer"
    assert {"company_name", "business_type", "scenario", "source_url", "quote", "published_at",
            "contact_entry_url", "fit_reason", "fit_score", "intent_score", "identity_status",
            "status", "reply_text", "next_action", "evidence"} <= first.keys()
    updated = upsert_company(store, "national-day", company(
        official_domain="acme.example", official_organization_id="registered-123", company_name="Renamed Acme"))
    assert updated["company_id"] == first["company_id"]
    by_id = upsert_company(store, "national-day", {"official_organization_id": "registered-123", "next_action": "Review"})
    assert by_id["company_id"] == first["company_id"]
    assert len(list_companies(store, "national-day")) == 1
    assert count(store, "polyv_campaign_history") == 3
    old = json.loads(store.connection.execute("SELECT payload FROM polyv_campaign_history ORDER BY recorded_at LIMIT 1").fetchone()[0])
    assert old["company_name"] == "Acme Training"
    assert campaign_summary(store, "national-day")["qualified_companies"] == 1


def test_same_name_different_official_identity_is_not_merged(store):
    a = upsert_company(store, "national-day", company(official_domain="a.example"))
    b = upsert_company(store, "national-day", company(official_domain="b.example"))
    assert a["company_id"] != b["company_id"]
    assert campaign_summary(store, "national-day")["qualified_companies"] == 2
    with pytest.raises(ValueError, match="Conflicting"):
        upsert_company(store, "national-day", company(company_id=b["company_id"], official_domain="a.example"))
    with pytest.raises(ValueError, match="reassigned"):
        upsert_company(store, "national-day", {"company_id": a["company_id"], "official_domain": "c.example"})
    with pytest.raises(ValueError, match="identity required"):
        upsert_company(store, "national-day", {"company_name": "Acme Training"})


def test_deterministic_organization_ids_and_authority_namespaces(store, tmp_path):
    a = upsert_company(store, "national-day", company(official_domain="", official_organization_id="123"))
    b = upsert_company(store, "national-day", company(official_domain="", official_organization_id="123",
                                                     organization_id_authority="another-registry"))
    assert a["company_id"] != b["company_id"]
    fresh = RadarStore(tmp_path / "fresh.sqlite3")
    initialize_campaign(fresh, "national-day", "enterprise")
    assert upsert_company(fresh, "national-day", company(official_domain="", official_organization_id="123"))["company_id"] == a["company_id"]
    fresh.close()


@pytest.mark.parametrize("field,value", [
    ("identity_status", "candidate"), ("official_domain", ""), ("source_url", ""),
    ("source_url", "javascript:alert(1)"), ("quote", ""), ("source_verified", False),
    ("source_verified", "true"), ("source_verified", 1), ("contact_entry_url", ""),
    ("scenario", ""), ("fit_reason", ""),
])
def test_promoted_incomplete_companies_stay_pending(store, field, value):
    row = upsert_company(store, "national-day", company(company_id="explicit", status="promote", **{field: value}))
    assert row["status"] == "pending"
    assert row["evidence"]["requested_status"] == "promote"
    summary = campaign_summary(store, "national-day")
    assert summary["qualified_companies"] == 0 and summary["pending_companies"] == 1


def test_competitor_exclusion_and_independent_age_activity(store):
    excluded = upsert_company(store, "national-day", company(business_type="video_competitor"))
    assert excluded["status"] == "excluded"
    assert campaign_summary(store, "national-day")["pending_companies"] == 0
    old_demand = upsert_company(store, "national-day", company(official_domain="another.example", demand_age_days=365,
                                                              active_status="active", intent_score=0))
    assert old_demand["active_status"] == "active" and old_demand["demand_age_days"] == 365
    assert old_demand["intent_score"] == 0 and old_demand["status"] == "qualified"


@pytest.mark.parametrize("score", [-1, 11, True, "9", float("nan"), float("inf")])
def test_invalid_scores_are_atomic(store, score):
    with pytest.raises(ValueError):
        upsert_company(store, "national-day", company(fit_score=score))
    assert list_companies(store, "national-day") == []
    assert count(store, "polyv_campaign_identities") == 0


def test_brand_and_campaign_isolation(store):
    a = upsert_company(store, "national-day", company())
    initialize_campaign(store, "another-campaign", "enterprise", target_companies=10, target_exchanges=1)
    b = upsert_company(store, "another-campaign", company())
    assert a["company_id"] == b["company_id"]
    link_outreach(store, "national-day", a["company_id"], outreach())
    record_exchange(store, "national-day", exchange(a["company_id"]))
    assert campaign_summary(store, "national-day")["effective_exchanges"] == 1
    other = campaign_summary(store, "another-campaign")
    assert other["contacted_companies"] == other["replied_companies"] == other["effective_exchanges"] == 0
    assert other["target_companies"] == 10 and other["target_exchanges"] == 1
    for action in (
        lambda: initialize_campaign(store, "zigo-sale", "enterprise"),
        lambda: upsert_company(store, "national-day", company(brand="Zigo")),
        lambda: upsert_company(store, "national-day", company(campaign_id="another-campaign")),
        lambda: link_outreach(store, "national-day", a["company_id"], outreach(brand="ZigoAI")),
        lambda: record_exchange(store, "national-day", exchange(a["company_id"], brand="Zigo")),
        lambda: record_exchange(store, "national-day", exchange(a["company_id"], campaign_id="another-campaign")),
    ):
        with pytest.raises(ValueError):
            action()


@pytest.mark.parametrize("field,value", [
    ("submitted", False), ("verified", False), ("own_account", False), ("target_relation", False),
    ("submitted", "true"), ("verified", 1), ("source_url", ""), ("quote", ""),
    ("own_account_id", ""), ("other_account_id", ""), ("actual_date", "not-a-date"),
    ("actual_date", "2099-10-01"),
    ("mode", "dry_run"), ("status", "draft"),
])
def test_unverified_outreach_never_counts(store, field, value):
    row = upsert_company(store, "national-day", company())
    event = link_outreach(store, "national-day", row["company_id"], outreach(**{field: value}))
    assert event["status"] == "pending" and event["counted"] is False
    assert campaign_summary(store, "national-day")["contacted_companies"] == 0


@pytest.mark.parametrize("field,value", [
    ("own_account_id", ""), ("other_account_id", "our-account"), ("other_quote", ""),
    ("source_url", ""), ("source_verified", False), ("target_relation", False),
    ("actual_date", ""), ("actual_date", "2099-10-01"),
    ("substantive_business_response", False), ("substantive_business_response", "true"),
    ("own_quote", ""), ("own_quote", "Thanks!"), ("other_quote", "Thanks!"),
    ("other_quote", "\u8c22\u8c22\u5206\u4eab\uff01"),
    ("other_quote", "Thanks for sharing!"), ("other_quote", "Thank you very much for your reply."),
    ("other_quote", "\u611f\u8c22\u60a8\u7684\u5206\u4eab\uff01"),
    ("other_quote", "\u8c22\u8c22\u8001\u5e08\u7684\u56de\u590d"),
])
def test_incomplete_or_courtesy_exchange_not_effective(store, field, value):
    row = upsert_company(store, "national-day", company())
    event = record_exchange(store, "national-day", exchange(row["company_id"], **{field: value}))
    assert event["counted"] is False
    assert campaign_summary(store, "national-day")["effective_exchanges"] == 0


def test_replays_follow_up_revisions_and_account_links_do_not_inflate(store):
    row = upsert_company(store, "national-day", company(reply_text="They want a demo", status="contacted",
                                                       contacted_companies=100))
    assert campaign_summary(store, "national-day")["replied_companies"] == 0
    for n in range(3):
        link_outreach(store, "national-day", row["company_id"], outreach(event_id=str(n), queue_id=n))
        record_exchange(store, "national-day", exchange(row["company_id"], event_id=str(n)))
    summary = campaign_summary(store, "national-day")
    assert {k: summary[k] for k in ("qualified_companies", "contacted_companies", "replied_companies", "effective_exchanges")} == dict(
        qualified_companies=1, contacted_companies=1, replied_companies=1, effective_exchanges=1)
    assert count(store, "interaction_events") == count(store, "polyv_campaign_events") == 2
    original = record_exchange(store, "national-day", exchange(row["company_id"]))
    updated = record_exchange(store, "national-day", exchange(row["company_id"], own_quote="Please confirm peak concurrency.",
                                                            actual_date="2026-10-01T10:00:00+08:00"))
    assert updated["event_id"] == original["event_id"]
    assert updated["interaction_id"] == original["interaction_id"]
    assert count(store, "interaction_events") == 2
    assert campaign_summary(store, "national-day")["effective_exchanges"] == 1
    assert count(store, "polyv_campaign_history") > 3


def test_verification_upgrade_downgrade_history_and_pending_company_gate(store):
    row = upsert_company(store, "national-day", company())
    pending = record_exchange(store, "national-day", exchange(row["company_id"], source_verified=False))
    verified = record_exchange(store, "national-day", exchange(row["company_id"]))
    assert pending["event_id"] == verified["event_id"]
    assert count(store, "interaction_events") == 1
    assert campaign_summary(store, "national-day")["effective_exchanges"] == 1
    record_exchange(store, "national-day", exchange(row["company_id"], other_quote="Thanks!"))
    summary = campaign_summary(store, "national-day")
    assert summary["effective_exchanges"] == 0 and summary["replied_companies"] == 1
    upsert_company(store, "national-day", {"company_id": row["company_id"], "source_verified": False})
    assert campaign_summary(store, "national-day")["replied_companies"] == 0
    assert count(store, "polyv_campaign_history") == 5


def test_unknown_company_and_campaign_cannot_create_events(store):
    with pytest.raises(ValueError, match="Unknown campaign company"):
        record_exchange(store, "national-day", exchange("missing"))
    with pytest.raises(ValueError, match="Unknown campaign"):
        upsert_company(store, "missing", company())
    assert count(store, "interaction_events") == 0


def test_persistence_after_reopen(store):
    row = upsert_company(store, "national-day", company())
    link_outreach(store, "national-day", row["company_id"], outreach())
    before = campaign_summary(store, "national-day")
    reopened = RadarStore(store.path)
    initialize_campaign(reopened, "national-day", "enterprise")
    assert campaign_summary(reopened, "national-day") == before
    assert list_companies(reopened, "national-day") == [row]
    reopened.close()
