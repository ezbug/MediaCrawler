"""Second-response template for a real reply received in private messages."""

from __future__ import annotations

import re

_POLYV_RULES = {
    "企业培训": {
        "diagnosis": "你现在更卡的是内容没人看，还是考核落不了地",
        "mechanism": "企业培训不是把资料发下去就结束了，常见断点在内容形式、观看权限和后续跟踪",
        "advice": "先把培训对象、人数、权限、学习记录和交付时间列清，再比较平台",
    },
    "企业直播": {
        "diagnosis": "你现在更担心的是并发稳定性，还是现场互动和应急保障",
        "mechanism": "大型直播的风险通常不在推流端，而在下行并发、网络抖动和现场应急",
        "advice": "先把活动时间、预计人数、观看对象、互动方式和应急安排列清，再做压力验证",
    },
    "私域直播": {
        "diagnosis": "你现在更卡的是私域触达，还是直播后的客户承接",
        "mechanism": "私域直播的关键不是单场热度，而是微信生态连通、权限控制和数据回传",
        "advice": "先把触达渠道、观看权限、互动方式和数据承接要求列清，再比较平台",
    },
    "视频点播": {
        "diagnosis": "你现在更在意的是跨端播放，还是权限和内容分发",
        "mechanism": "企业点播常见问题集中在转码适配、播放体验和防盗链",
        "advice": "先把视频规模、观看范围、权限要求和终端场景列清，再确认托管和集成方案",
    },
    "视频安全": {
        "diagnosis": "你现在更需要防下载、防录屏，还是泄露后的溯源能力",
        "mechanism": "只靠禁右键或普通密码挡不住录屏，通常还要结合动态水印和权限控制",
        "advice": "先把观看权限、分发范围、下载限制和追溯要求列清，再向平台确认安全能力",
    },
    "AI视频": {
        "diagnosis": "你现在更卡的是课件整理，还是批量产出和审核",
        "mechanism": "批量做视频的难点通常不在生成，而在课件结构、讲稿审核和统一交付",
        "advice": "先把课件来源、审核方式、产出数量和交付时间列清，再比较工具和平台衔接",
    },
    "技术集成": {
        "diagnosis": "你现在更关注接入周期、并发预期，还是现有系统兼容",
        "mechanism": "自建直播最容易低估的是多端适配、并发压力、权限和后续维护",
        "advice": "先把已有系统、接入端、接口要求、并发和交付周期列清，再比较集成方案",
    },
    "出海": {
        "diagnosis": "你现在更担心的是跨地域网络，还是多语言观看体验",
        "mechanism": "海外直播常见问题是链路抖动、区域差异和多语言传达不到位",
        "advice": "先把覆盖地区、语言、观看对象、活动时间和服务要求列清，再确认支持范围",
    },
}

_DEFAULT_POLYV = {
    "diagnosis": "你现在更卡的是场景梳理，还是平台选型",
    "mechanism": "这类需求通常要先把人数、权限、交付时间和使用场景厘清，再判断平台能力是否匹配",
    "advice": "先把业务场景、人数、权限、交付时间和预算范围列清，再比较方案",
}

_DEFAULT_ZIGO = {
    "diagnosis": "你现在更卡的是线索接不住、跟进断档，还是转化复盘没有抓手",
    "mechanism": "销售执行问题通常不是一个工具就能解决，先看响应速度、线索分层和跟进提醒",
    "advice": "先把线索来源、团队规模、首响时长和跟进流程列清，再比较方案",
}


def build_follow_up_reply(
    incoming_text: str,
    category: str = "",
    *,
    domain: str = "polyv",
    brand: str = "POLYV",
) -> str:
    """Build the old structured reply format for a DM follow-up."""
    clean = re.sub(r"\s+", " ", str(incoming_text or "")).strip().strip("。")[:120]
    if domain == "zigo_sales":
        rule = _DEFAULT_ZIGO
        scope = "销售接待和跟进"
    else:
        rule = _POLYV_RULES.get(category, _DEFAULT_POLYV)
        scope = category or "企业视频与直播"
    return (
        f"你说的“{clean}”这个情况，我大概明白了。"
        f"{rule['diagnosis']}？"
        f"{rule['mechanism']}。"
        f"建议{rule['advice']}。"
        f"我们这边做{scope}（{brand}），有相应的产品和丰富案例指导，也有客户实际成功经验，可以按你的场景帮你对一下方案；"
        "方便的话补充一下行业、人数或线索量、以及期望的交付时间。"
    )
