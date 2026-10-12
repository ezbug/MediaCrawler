"""Short second-response template for private-message follow-ups.

The five-part reasoning stays internal. The sent reply is capped at twenty
Chinese characters and keeps only one action plus a light handoff.
"""

from __future__ import annotations

import re

FOLLOW_UP_LIMIT = 20

_SHORT_ACTIONS = {
    "企业培训": "内容和学习记录",
    "企业直播": "并发和应急",
    "私域直播": "触达和承接",
    "视频点播": "播放和权限",
    "视频安全": "水印和权限",
    "AI视频": "课件和审核",
    "技术集成": "接口和并发",
    "出海": "链路和语言",
}

_DEFAULT_POLYV = "场景和交付"
_DEFAULT_ZIGO = "首响和线索分层"


def char_count(value: str) -> int:
    return len(re.sub(r"\W+", "", str(value or "")))


def build_follow_up_reply(
    incoming_text: str,
    category: str = "",
    *,
    domain: str = "polyv",
    brand: str = "",
) -> str:
    """Build a short second reply after the other side answers."""
    del incoming_text, brand
    action = _DEFAULT_ZIGO if domain == "zigo_sales" else _SHORT_ACTIONS.get(category, _DEFAULT_POLYV)
    text = f"先看{action}，我帮你对方案"
    if char_count(text) > FOLLOW_UP_LIMIT:
        raise ValueError("follow-up reply exceeds 20 Chinese characters")
    return text
