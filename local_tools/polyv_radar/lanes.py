"""Lane isolation: buyer demand vs provider outreach vs institutional demand.

The handoff requires the three record types to be counted separately and never
to pad each other:

* ``buyer_demand``          — social buyer intent; candidate needs score >= 4
* ``provider_outreach``     — interactions under provider / industry content;
                              **never counted as buyer prospects**
* ``institutional_demand``  — public procurement / need announcements;
                              **never counted as social send targets**

Design rules
------------
* A record is assigned to at most ONE lane. A record carrying two conflicting
  lane signals raises :class:`LaneConflictError` instead of being silently
  bucketed (silent bucketing is how counts drift).
* Records with no documented signal are ``unclassified`` — they are never
  promoted into ``buyer_demand`` just to look useful.
* ``counts_by_lane`` counts every row exactly once, so the total equals the
  number of input rows: nothing is lost and nothing is double counted.
"""

from __future__ import annotations

from typing import Iterable, Mapping

LANES = ("buyer_demand", "provider_outreach", "institutional_demand")
UNCLASSIFIED = "unclassified"

#: Buyers must clear the shared high-value threshold (review.HIGH_VALUE_THRESHOLD).
BUYER_MIN_SCORE = 4

SOCIAL_SOURCE_TYPES = ("comment", "reply", "post", "answer", "content")

#: Fields that only ever appear on the institutional demand ledger.
INSTITUTIONAL_MARKERS = ("bucket", "org_full_name", "demand_quote")

#: `source_role` returned by scoring.classify_publisher_role for provider accounts.
PROVIDER_ROLES = ("likely_provider",)

#: Campaign id fragments that mean "this batch is provider outreach".
PROVIDER_CAMPAIGN_MARKERS = ("provider", "provider-social")


class LaneConflictError(ValueError):
    """A record carries signals for more than one lane."""


def _text(value: object) -> str:
    return str(value or "").strip().casefold()


def _row_value(row: Mapping | object, *names: str) -> str:
    for name in names:
        if isinstance(row, Mapping):
            if name in row and row[name] not in (None, ""):
                return str(row[name])
        else:
            value = getattr(row, name, None)
            if value not in (None, ""):
                return str(value)
    return ""


def has_institutional_signal(row: Mapping | object) -> bool:
    if any(_row_value(row, name) for name in INSTITUTIONAL_MARKERS):
        return True
    return _text(_row_value(row, "lane")) == "institutional_demand"


def has_provider_signal(row: Mapping | object) -> bool:
    role = _text(_row_value(row, "source_role"))
    if role in PROVIDER_ROLES:
        return True
    campaign = _text(_row_value(row, "campaign_id", "campaign"))
    if campaign and any(marker in campaign for marker in PROVIDER_CAMPAIGN_MARKERS):
        return True
    return _text(_row_value(row, "lane")) == "provider_outreach"


def has_buyer_signal(row: Mapping | object) -> bool:
    explicit = _text(_row_value(row, "lane"))
    if explicit == "buyer_demand":
        return True
    source_type = _text(_row_value(row, "source_type"))
    if source_type and source_type not in SOCIAL_SOURCE_TYPES:
        return False
    # a social record that is not a provider or institutional record is buyer-side
    return bool(_row_value(row, "target_url") or _row_value(row, "url"))


def classify_lane(row: Mapping | object) -> str:
    """Assign exactly one lane, or ``unclassified``. Never guesses.

    Order of resolution:

    1. an explicit ``lane`` field wins, but only if it is a valid lane name —
       an unknown label is rejected rather than silently ignored;
    2. institutional and provider signals are *specific*; if a record carries
       both, that is a genuine conflict and is escalated instead of being
       silently bucketed;
    3. otherwise a plain social record with a locatable target is
       ``buyer_demand``;
    4. anything else stays ``unclassified`` and can never pad a buyer count.
    """
    explicit = _text(_row_value(row, "lane"))
    if explicit:
        if explicit not in LANES:
            raise ValueError(f"未知类型标签：{explicit}")
        return explicit

    institutional = has_institutional_signal(row)
    provider = has_provider_signal(row)
    if institutional and provider:
        raise LaneConflictError(
            "记录同时命中机构需求与服务商互动，需人工裁决："
            "['institutional_demand', 'provider_outreach']"
        )
    if institutional:
        return "institutional_demand"
    if provider:
        return "provider_outreach"
    if has_buyer_signal(row):
        return "buyer_demand"
    return UNCLASSIFIED


def counts_by_lane(rows: Iterable[Mapping | object]) -> dict[str, int]:
    """Count every row exactly once. ``sum(result.values()) == len(rows)``."""
    counts = {lane: 0 for lane in LANES}
    counts[UNCLASSIFIED] = 0
    for row in rows:
        counts[classify_lane(row)] += 1
    return counts


def _score(row: Mapping | object) -> int:
    raw = _row_value(row, "rule_score", "score")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return -1


def buyer_candidates(rows: Iterable[Mapping | object]) -> list:
    """Buyer prospects: buyer lane, score >= 4, with a locatable target."""
    result = []
    for row in rows:
        if classify_lane(row) != "buyer_demand":
            continue
        if _score(row) < BUYER_MIN_SCORE:
            continue
        if not (_row_value(row, "target_url") or _row_value(row, "url")):
            continue
        result.append(row)
    return result


def provider_interactions(rows: Iterable[Mapping | object]) -> list:
    return [row for row in rows if classify_lane(row) == "provider_outreach"]


def institutional_records(rows: Iterable[Mapping | object]) -> list:
    return [row for row in rows if classify_lane(row) == "institutional_demand"]


def social_send_targets(rows: Iterable[Mapping | object]) -> list:
    """Records eligible to be social send targets.

    Institutional announcements are excluded by definition: an institution's
    procurement notice is not a social account to reply to.
    """
    return [
        row for row in rows
        if classify_lane(row) in ("buyer_demand", "provider_outreach")
    ]
