"""Structured second response for private-message follow-ups.

The five-part structure stays intact. Each sentence is capped at twenty
Chinese characters. No company or brand name is exposed, and no contact or
private-message prompt is added.
"""

from __future__ import annotations

import re

SENTENCE_LIMIT = 20

_RULES = {
    "企业培训": {
        "ack": "你这个情况我懂",
        "diagnosis": "多半卡在内容和跟踪上",
        "mechanism": "资料发了没人看，权限和反馈也容易断",
        "advice": "先理对象、权限和学习记录",
        "invite": "先按这个顺序梳理",
    },
    "企业直播": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点一般在并发和应急上",
        "mechanism": "人一多，卡顿和抖动最容易暴露",
        "advice": "先理人数、互动和应急安排",
        "invite": "先按这个顺序梳理",
    },
    "私域直播": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点在触达和后续承接上",
        "mechanism": "直播结束，客户承接才刚开始",
        "advice": "先理渠道、权限和数据回流",
        "invite": "先按这个顺序梳理",
    },
    "视频点播": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点在播放和权限上",
        "mechanism": "转码适配和防盗链最容易出问题",
        "advice": "先理视频量、终端和权限",
        "invite": "先按这个顺序梳理",
    },
    "视频安全": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点是防录屏和溯源",
        "mechanism": "只禁右键挡不住录屏",
        "advice": "先理权限、下载限制和追溯",
        "invite": "先按这个顺序梳理",
    },
    "AI视频": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点在课件和审核上",
        "mechanism": "批量产出难在讲稿和审核",
        "advice": "先理课件来源、数量和交付",
        "invite": "先按这个顺序梳理",
    },
    "技术集成": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点在接口和并发上",
        "mechanism": "自建常低估多端适配和维护",
        "advice": "先理系统、接口和并发预期",
        "invite": "先按这个顺序梳理",
    },
    "出海": {
        "ack": "你这个情况我懂",
        "diagnosis": "重点在链路和语言上",
        "mechanism": "跨地域抖动和多语言最容易出问题",
        "advice": "先理地区、语言和活动时间",
        "invite": "先按这个顺序梳理",
    },
}

_DEFAULT_POLYV = {
    "ack": "你这个情况我懂",
    "diagnosis": "重点在场景和交付上",
    "mechanism": "人数、权限和交付时间要先厘清",
    "advice": "先理场景、人数和预算",
    "invite": "先按这个顺序梳理",
}

_DEFAULT_ZIGO = {
    "ack": "你这个情况我懂",
    "diagnosis": "重点在响应和跟进上",
    "mechanism": "线索接不住常不是一个人的问题",
    "advice": "先理来源、首响和分层",
    "invite": "先按这个顺序梳理",
}

_FORBIDDEN = ("私信我", "找我", "私聊", "细聊", "POLYV", "ZigoAI")


def char_count(value: str) -> int:
    return len(re.sub(r"\W+", "", str(value or "")))


def _sentence(value: str) -> str:
    value = str(value or "").strip().strip("。")
    if char_count(value) > SENTENCE_LIMIT:
        raise ValueError("follow-up sentence exceeds 20 Chinese characters")
    return f"{value}。"


def build_follow_up_reply(
    incoming_text: str,
    category: str = "",
    *,
    domain: str = "polyv",
) -> str:
    """Build a five-part second reply, one sentence per part."""
    del incoming_text
    rule = _DEFAULT_ZIGO if domain == "zigo_sales" else _RULES.get(category, _DEFAULT_POLYV)
    text = "".join(
        _sentence(rule[key])
        for key in ("ack", "diagnosis", "mechanism", "advice", "invite")
    )
    if any(term in text for term in _FORBIDDEN):
        raise ValueError("follow-up reply exposes a forbidden term")
    return text
