"""Comment-first short reply wording for public comments.

Public comment replies stay within ten Chinese characters, avoid brand names,
and do one of two jobs: give a short solution or gently invite a reply.
Opening lines pass through a small humanizer-zh style pass: no interrogation
ending, no corporate filler, and no template-sounding question.
"""

from __future__ import annotations

import re

TOTAL_COMMENT_LIMIT = 10
PEER_VARIANT_LIMIT = 12

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
    (re.compile(r"报价|价格|预算"), "我也卡过，后来还好吗？"),
    (re.compile(r"客户|线索|跟进|转化|开单|成交"), "我也遇到过，后来还好吗？"),
    (re.compile(r"工具|软件|系统|AI|ai"), "同行，后来顺利吗？"),
)

_PEER_FALLBACK = "后来还顺利吗？"

_BLUNT_TERMS = ("解决没", "解决了吗", "懂了吗", "明白没")
_SISTER_TERMS = re.compile(r"姐妹|宝妈|女生|女性|小姐姐")
_SISTER_PROBE = "后来是怎么解决的啊，姐妹"


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
    """Use solve mode for explicit questions; otherwise use a peer probe."""
    text = str(quote or "")
    if re.search(r"怎么办|怎么选|怎么跟|怎么收费|什么价格|多少钱|什么软件|怎么部署|求推荐|预算|采购|报价|想了解|能不能|如何|有没有", text):
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
    """Build one short public comment with no company or product name."""
    mode = mode or choose_mode(quote)
    if variant == "sister" or (mode != "solve" and _SISTER_TERMS.search(str(quote or ""))):
        if first_line_chars(_SISTER_PROBE) > PEER_VARIANT_LIMIT:
            raise ValueError("sister peer probe exceeds approved limit")
        return _SISTER_PROBE
    if mode == "solve":
        phrase = _SOLVE_PHRASES.get(category, _DEFAULT_SOLVE)
    else:
        industry_name = str(industry or "").strip()
        phrase = f"{industry_name}同行，后来顺利吗？" if industry_name else _PEER_FALLBACK
        if first_line_chars(phrase) > TOTAL_COMMENT_LIMIT:
            phrase = _PEER_FALLBACK
        for pattern, opener in _PEER_BY_QUOTE:
            if pattern.search(str(quote or "")):
                if not industry_name or first_line_chars(f"{industry_name}同行，后来顺利吗？") > TOTAL_COMMENT_LIMIT:
                    phrase = opener
                break
    if first_line_chars(phrase) > TOTAL_COMMENT_LIMIT:
        raise ValueError("comment reply exceeds 10 Chinese characters")
    return humanize_opening(phrase)


def reactivation_comment(quote: str, category: str) -> str:
    """One short historical-reactivation question; no brand name."""
    del quote, category
    return "现在还有遇到什么问题吗？"
