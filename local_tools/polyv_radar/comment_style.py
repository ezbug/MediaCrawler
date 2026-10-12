"""Comment-first reply wording for public comment replies.

The first line is kept short so a reply opens like a native comment instead
of a marketing paragraph. Punctuation is ignored when enforcing the limit.
"""

from __future__ import annotations

import re

FIRST_LINE_LIMIT = 10

_SOLVE_OPENERS = (
    "这个真挺难",
    "同款问题",
    "我也遇到过",
    "这情况常见",
    "确实挺头疼",
    "先别急着换",
    "这题真不好答",
)

_REACTION_OPENERS = (
    "真是客户问题？",
    "这锅该谁背？",
    "换你你会忍？",
    "问题真在工具？",
    "老板会认吗？",
    "先别急着买",
)

_CATEGORY_STEPS = {
    "企业培训": "先把培训对象、人数、内容权限和交付时间列清",
    "企业直播": "先把活动时间、预计人数、观看对象和应急安排列清",
    "私域直播": "先把触达渠道、观看权限和数据承接要求列清",
    "视频点播": "先把视频规模、观看范围、权限和终端场景列清",
    "视频安全": "先把观看权限、内容分发、下载限制和追溯要求列清",
    "AI视频": "先把课件来源、审核方式、产出数量和交付时间列清",
    "技术集成": "先把现有系统、接入端、接口要求、并发和交付周期列清",
    "出海": "先把覆盖地区、语言、观看对象、活动时间和服务要求列清",
}

_DEFAULT_STEP = "先把业务场景、人数、权限、交付时间和预算范围列清"

_REACTION_BY_QUOTE = (
    (re.compile(r"不回|沉默|已读"), "真是客户问题？"),
    (re.compile(r"报价|价格|预算"), "真是价格问题？"),
    (re.compile(r"工具|软件|系统|AI|ai"), "问题真在工具？"),
    (re.compile(r"老板|管理|团队"), "老板会认吗？"),
)


def first_line_chars(value: str) -> int:
    """Count Chinese characters in the first line, ignoring punctuation."""
    return len(re.sub(r"\W+", "", str(value or "")))


def _pick(options: tuple[str, ...], seed: str) -> str:
    return options[sum(ord(ch) for ch in str(seed or "")) % len(options)]


def choose_mode(quote: str) -> str:
    """Choose solve mode for explicit questions, reaction mode otherwise."""
    text = str(quote or "")
    if re.search(r"怎么办|怎么选|怎么跟|怎么收费|什么价格|多少钱|什么软件|怎么部署|求推荐|预算|采购|报价|想了解|能不能|如何|有没有", text):
        return "solve"
    return "reaction"


def first_line(quote: str, mode: str | None = None) -> str:
    """Return a native-comment opener that stays within the character limit."""
    mode = mode or choose_mode(quote)
    if mode == "solve":
        return _pick(_SOLVE_OPENERS, quote)
    for pattern, opener in _REACTION_BY_QUOTE:
        if pattern.search(str(quote or "")):
            return opener
    return _pick(_REACTION_OPENERS, quote)


def comment_reply(
    quote: str,
    category: str,
    *,
    brand: str = "POLYV",
    mode: str | None = None,
) -> str:
    """Build a short public comment reply without a corporate preamble."""
    clean = re.sub(r"\s+", " ", str(quote or "")).strip().strip("。")[:70]
    mode = mode or choose_mode(clean)
    opener = first_line(clean, mode)
    if first_line_chars(opener) > FIRST_LINE_LIMIT:
        raise ValueError("comment first line exceeds 10 Chinese characters")
    opening = opener if opener.endswith(("？", "！", "?")) else f"{opener}。"
    if mode == "solve":
        step = _CATEGORY_STEPS.get(category, _DEFAULT_STEP)
        return f"{opening}你提到“{clean}”，{step}。{brand}可以按你们的场景帮你梳理。"
    return f"{opening}你提到“{clean}”，想听听你后来怎么处理的。{brand}这边也在看这类问题。"


def reactivation_comment(
    quote: str,
    category: str,
    *,
    brand: str = "POLYV",
) -> str:
    """Short historical-reactivation reply with a native first line."""
    clean = re.sub(r"\s+", " ", str(quote or "")).strip().strip("。")[:70]
    return (
        "现在这方面还有需求吗？"
        f"之前你说“{clean}”，如果还在推进，{brand}可以按{category}的实际场景帮你梳理；"
        "方便的话可以私信沟通。"
    )
