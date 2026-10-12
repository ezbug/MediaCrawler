"""Comment-first short reply wording for public comments.

Public comment replies stay within ten Chinese characters, avoid brand names,
and do one of two jobs: give a short solution or provoke a reply.
"""

from __future__ import annotations

import re

TOTAL_COMMENT_LIMIT = 10

_SOLVE_PHRASES = {
    "企业培训": "先看培训流程",
    "企业直播": "先看直播方案",
    "私域直播": "先看私域承接",
    "视频点播": "先看点播方案",
    "视频安全": "先看防盗录流程",
    "AI视频": "先做内容审核",
    "技术集成": "先看接入方案",
    "出海": "先看海外链路",
}

_DEFAULT_SOLVE = "先看具体流程"

_PEER_BY_QUOTE = (
    (re.compile(r"报价|价格|预算"), "我也卡过，解决没？"),
    (re.compile(r"客户|线索|跟进|转化|开单|成交"), "我也遇到过，解决没？"),
    (re.compile(r"工具|软件|系统|AI|ai"), "同行，解决了吗？"),
)

_PEER_FALLBACK = "后来解决了吗？"


def first_line_chars(value: str) -> int:
    """Count Chinese characters, ignoring punctuation."""
    return len(re.sub(r"\W+", "", str(value or "")))


def choose_mode(quote: str) -> str:
    """Use solve mode for explicit questions; otherwise use a peer probe."""
    text = str(quote or "")
    if re.search(r"怎么办|怎么选|怎么跟|怎么收费|什么价格|多少钱|什么软件|怎么部署|求推荐|预算|采购|报价|想了解|能不能|如何|有没有", text):
        return "solve"
    return "reaction"


def comment_reply(
    quote: str,
    category: str,
    *,
    mode: str | None = None,
) -> str:
    """Build one short public comment with no company or product name."""
    mode = mode or choose_mode(quote)
    if mode == "solve":
        phrase = _SOLVE_PHRASES.get(category, _DEFAULT_SOLVE)
    else:
        phrase = _PEER_FALLBACK
        for pattern, opener in _PEER_BY_QUOTE:
            if pattern.search(str(quote or "")):
                phrase = opener
                break
    if first_line_chars(phrase) > TOTAL_COMMENT_LIMIT:
        raise ValueError("comment reply exceeds 10 Chinese characters")
    return phrase


def reactivation_comment(quote: str, category: str) -> str:
    """One short historical-reactivation question; no brand name."""
    del quote, category
    return "现在还要做吗？"
