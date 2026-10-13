"""Comment-first reply wording for public comments.

Replies praise the target's content first, stay within fifteen Chinese
characters, carry at most one compressed line of guidance, and avoid brand,
product and industry wording.  Commercial identity stays out of public
comments; full mechanics and evidence boundaries stay in internal fields.
"""

from __future__ import annotations

import re

COMMENT_LIMIT = 15

_PRAISE_SOLVE = "问得好"
_PRAISE_CONTENT = "讲得好"
_PRAISE_REACTION = "说得太真实了"
_PRAISE_HISTORY = "讲得在理"

_SOLVE_PROBE = "后来怎么解决的？"
_PEER_PROBE = "后来顺利吗？"
_SISTER_PROBE = "后来咋解决的啊姐妹"
_REACTIVATION_PROBE = "现在还有这问题吗？"

COMMENT_GUIDANCE = {
    "企业培训": "人数权限先理清",
    "企业直播": "人数应急先定好",
    "私域直播": "权限数据先对齐",
    "视频点播": "分发权限先想清",
    "视频安全": "权限追溯先理清",
    "AI视频": "流程审核先定好",
    "技术集成": "接口并发先对齐",
    "出海": "地区语言先确认",
}
_DEFAULT_GUIDANCE = "场景人数先理清"

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


def category_comment_guidance(category: str) -> str:
    """Compressed one-line guidance used inside short public comments."""
    return COMMENT_GUIDANCE.get(str(category or "").strip(), _DEFAULT_GUIDANCE)


def praise_for_mode(mode: str) -> str:
    """Pick the praise opener for the comment mode."""
    if mode == "solve":
        return _PRAISE_SOLVE
    if mode == "reaction":
        return _PRAISE_REACTION
    return _PRAISE_CONTENT


def comment_reply(
    quote: str,
    category: str,
    *,
    industry: str = "",
    mode: str | None = None,
    variant: str = "",
    guidance: str = "",
) -> str:
    """Build one praise-first public comment within fifteen Chinese characters.

    The guidance argument carries the compressed half-sentence of the
    internal guidance; when provided it replaces the question tail so the
    comment itself covers the advice.  Brand, product and industry wording
    always stay out.
    """
    del category, industry
    mode = mode or choose_mode(quote)
    praise = praise_for_mode(mode)
    if guidance:
        tail = str(guidance).strip().rstrip("。")
    elif variant == "sister" or (mode != "solve" and _SISTER_TERMS.search(str(quote or ""))):
        tail = _SISTER_PROBE
    elif mode == "solve":
        tail = _SOLVE_PROBE
    else:
        tail = _PEER_PROBE
    phrase = humanize_opening(f"{praise}，{tail}")
    if first_line_chars(phrase) > COMMENT_LIMIT:
        raise ValueError("comment reply exceeds 15 Chinese characters")
    return phrase


def reactivation_comment(quote: str, category: str) -> str:
    """Praise-first historical-reactivation question; no brand name."""
    del quote, category
    return f"{_PRAISE_HISTORY}，{_REACTIVATION_PROBE}"
