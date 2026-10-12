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

_REACTION_BY_QUOTE = (
    (re.compile(r"不回|沉默|已读"), "真是客户问题？"),
    (re.compile(r"报价|价格|预算"), "真是价格问题？"),
    (re.compile(r"工具|软件|系统|AI|ai"), "问题真在工具？"),
    (re.compile(r"老板|管理|团队"), "老板会认吗？"),
)

_REACTION_FALLBACK = "这锅谁背？"


def first_line_chars(value: str) -> int:
    """Count Chinese characters, ignoring punctuation."""
    return len(re.sub(r"\W+", "", str(value or "")))


def choose_mode(quote: str) -> str:
    """Use solve mode for explicit questions; otherwise provoke a reply."""
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
        phrase = _REACTION_FALLBACK
        for pattern, opener in _REACTION_BY_QUOTE:
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
