"""Comment-first reply wording for public comments.

Replies stay within twenty Chinese characters, avoid brand and industry
wording, and use a shared-experience opener instead of a solution checklist.
"""

from __future__ import annotations

import re

COMMENT_LIMIT = 20

_SOLVE_PROBE = "想问问具体咋样的？我之前也有类似问题"
_PEER_PROBE = "我也遇到了一样的问题，后来顺利吗？"
_SISTER_PROBE = "后来是怎么解决的啊，姐妹"

_BLUNT_TERMS = ("解决没", "解决了吗", "懂了吗", "明白没")
_SISTER_TERMS = re.compile(r"姐妹|宝妈|女生|女性|小姐姐")


def humanize_opening(text: str) -> str:
    """Apply a small humanizer-zh pass to short opening replies."""
    value = str(text or "").strip()
    for term in _BLUNT_TERMS:
        value = value.replace(term, "后来还好吗")
    return value


def first_line_chars(value: str) -> int:
    """Count Chinese characters, ignoring punctuation."""
    return len(re.sub(r"\W+", "", str(value or "")))


def choose_mode(quote: str) -> str:
    """Keep the old mode split for compatibility; both use shared experience."""
    text = str(quote or "")
    if re.search(r"怎么|如何|什么价格|多少钱|什么软件|求推荐|预算|采购|报价|想了解|能不能|有没有", text):
        return "solve"
    return "reaction"


def comment_reply(
    quote: str,
    category: str,
    *,
    industry: str = "",
    mode: str | None = None,
    variant: str = "",
) -> str:
    """Build one short public comment with no brand or industry wording."""
    del category, industry
    mode = mode or choose_mode(quote)
    if variant == "sister" or (mode != "solve" and _SISTER_TERMS.search(str(quote or ""))):
        phrase = _SISTER_PROBE
    elif mode == "solve":
        phrase = _SOLVE_PROBE
    else:
        phrase = _PEER_PROBE
    if first_line_chars(phrase) > COMMENT_LIMIT:
        raise ValueError("comment reply exceeds 20 Chinese characters")
    return humanize_opening(phrase)


def reactivation_comment(quote: str, category: str) -> str:
    """One short historical-reactivation question; no brand name."""
    del quote, category
    return "现在还有遇到什么问题吗？"
