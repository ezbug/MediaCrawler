"""Classify who replied to a radar comment.

The reply stream mixes very different conversations. Keeping them apart is a
data-integrity rule, not cosmetics:

* prospect - a user or business replying to our POLYV/Zigo sales comment;
* peer - a competitor answering our peer-research (友商探针) probe. The
  keyword list is sourced from the enterprise-crawler peer ledger
  (peer-research), e.g. 小鹅通 / 创客匠人 / 伯索(爱问云). These replies are
  probe results, not leads;
* artifact - processing output of our own crawler: our own account names
  appearing as the "replier", echoes of our published comments;
* unknown - the replier could not be determined.

Defaults to prospect for unmatched names because a human replying to a sales
comment is the normal case; peers are a closed, named set.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).with_name("reply_class_rules.json")

CLASS_LABELS = {
    "prospect": "用户回复",
    "peer": "友商探针",
    "artifact": "处理信息",
    "unknown": "未分类",
}


def _normalize(name: object) -> str:
    return re.sub(r"\s+", "", str(name or "")).casefold()


@lru_cache(maxsize=4)
def load_rules(path: Path | str = RULES_PATH) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload.setdefault("peer_keywords", [])
    payload.setdefault("self_keywords", [])
    return payload


def classify_reply_author(name: object, rules: dict | None = None) -> tuple[str, str]:
    """Return (code, label) for a replier display name."""
    normalized = _normalize(name)
    if not normalized:
        return "unknown", CLASS_LABELS["unknown"]
    active = rules if rules is not None else load_rules()
    for keyword in active.get("self_keywords", []):
        if _normalize(keyword) and _normalize(keyword) in normalized:
            return "artifact", CLASS_LABELS["artifact"]
    for keyword in active.get("peer_keywords", []):
        if _normalize(keyword) and _normalize(keyword) in normalized:
            return "peer", CLASS_LABELS["peer"]
    return "prospect", CLASS_LABELS["prospect"]
