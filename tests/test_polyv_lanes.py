"""Type isolation: buyer demand, provider outreach and institutional demand
must never pad each other's counts.
"""

from __future__ import annotations

import pytest

from local_tools.polyv_radar.lanes import (
    BUYER_MIN_SCORE,
    LANES,
    UNCLASSIFIED,
    LaneConflictError,
    buyer_candidates,
    classify_lane,
    counts_by_lane,
    institutional_records,
    provider_interactions,
    social_send_targets,
)


def _social(**overrides) -> dict:
    base = {
        "platform": "zhihu",
        "target_url": "https://zhuanlan.zhihu.com/p/1",
        "target_author": "企业HR",
        "target_quote": "公司需要培训平台，预算怎么算？",
        "source_type": "comment",
        "rule_score": 5,
    }
    base.update(overrides)
    return base


def _provider(**overrides) -> dict:
    base = _social(source_role="likely_provider", campaign_id="20260928-provider-social30")
    base.update(overrides)
    return base


def _institutional(**overrides) -> dict:
    base = {
        "id": "lead-ujs-live-train",
        "bucket": "可核验需求线索",
        "org_full_name": "江苏开放大学",
        "demand_quote": "采购课程直播服务",
        "sales_priority": "P0",
    }
    base.update(overrides)
    return base


# --- classification -------------------------------------------------------


def test_three_lanes_are_recognised() -> None:
    assert classify_lane(_social()) == "buyer_demand"
    assert classify_lane(_provider()) == "provider_outreach"
    assert classify_lane(_institutional()) == "institutional_demand"


def test_unknown_records_stay_unclassified() -> None:
    """No signal must never be promoted into buyer_demand."""
    assert classify_lane({"foo": "bar"}) == UNCLASSIFIED
    assert classify_lane({"source_type": "comment"}) == UNCLASSIFIED


def test_conflicting_lane_signals_raise_instead_of_double_counting() -> None:
    conflicted = _social(source_role="likely_provider", bucket="可核验需求线索")
    with pytest.raises(LaneConflictError):
        classify_lane(conflicted)


def test_explicit_lane_is_respected() -> None:
    assert classify_lane(_social(lane="provider_outreach")) == "provider_outreach"


# --- isolation guarantees -------------------------------------------------


def test_counts_by_lane_is_lossless_and_double_count_free() -> None:
    rows = [
        _social(),
        _social(target_url="https://zhuanlan.zhihu.com/p/2"),
        _provider(),
        _institutional(),
        {"foo": "bar"},
    ]
    counts = counts_by_lane(rows)
    assert sum(counts.values()) == len(rows)
    assert counts["buyer_demand"] == 2
    assert counts["provider_outreach"] == 1
    assert counts["institutional_demand"] == 1
    assert counts[UNCLASSIFIED] == 1
    for lane in LANES:
        assert lane in counts


def test_provider_interactions_are_never_buyer_candidates() -> None:
    rows = [_provider(), _social()]
    buyers = buyer_candidates(rows)
    providers = provider_interactions(rows)

    assert len(providers) == 1
    assert len(buyers) == 1
    assert buyers[0].get("source_role") != "likely_provider"
    # no overlap between the two sets
    assert not set(map(id, buyers)) & set(map(id, providers))


def test_institutional_records_are_never_social_send_targets() -> None:
    rows = [_institutional(), _social(), _provider()]
    targets = social_send_targets(rows)
    institutional = institutional_records(rows)

    assert len(institutional) == 1
    assert len(targets) == 2
    for row in targets:
        assert "bucket" not in row


def test_buyer_candidates_require_the_score_threshold() -> None:
    below = _social(rule_score=BUYER_MIN_SCORE - 1)
    at = _social(rule_score=BUYER_MIN_SCORE)
    assert buyer_candidates([below]) == []
    assert len(buyer_candidates([at])) == 1


def test_buyer_candidates_require_a_locatable_target() -> None:
    rows = [_social(target_url="")]
    assert buyer_candidates(rows) == []


def test_provider_campaign_id_alone_marks_the_lane() -> None:
    """A whole provider campaign is provider outreach even without source_role."""
    row = _social(campaign_id="20260928-provider-social30")
    row.pop("source_role", None)
    assert classify_lane(row) == "provider_outreach"
    assert buyer_candidates([row]) == []
