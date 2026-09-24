from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import LeadEvidence


@dataclass
class ConversionPack:
    reply_text: str
    video_topic: str
    video_hook: str
    dm_opener: str
    recommended_materials: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply_text": self.reply_text,
            "video_topic": self.video_topic,
            "video_hook": self.video_hook,
            "dm_opener": self.dm_opener,
            "recommended_materials": self.recommended_materials,
        }


KNOWLEDGE_BASE = {
    "企业培训": {
        "reply_template": (
            "企业内训和新人带教最容易踩的坑就是“课件发了没人看，考核流于形式”。"
            "目前业内更有效的做法是把核心 SOP 和 PPT 转为互动微课或短视频切片，"
            "嵌入到企微或飞书里，配合学习记录、权限控制和防录屏播放器，便于持续跟踪学习效果。"
        ),
        "video_topic": "企业做内训最容易踩的3个坑：为什么发了资料根本没人学？",
        "video_hook": "培训课件发到员工群里却没人学？很多管理者第一步就搞错了！",
        "dm_opener": (
            "你好，看到你在探讨企业培训落地的问题。我们整理了一份《企业微课与数字化培训落地方案SOP》，"
            "可以按人数、权限、学习记录和内容分发场景做选型参考。"
        ),
        "case": "[待核实] 企业线上培训与通关考核案例，客户名称和数据需经批准后补充",
        "template": "《企业数字化培训实施 SOP 与效果评估表.pdf》",
        "demo": "POLYV PPT 智能转微课 / 在线通关考核播放器体验",
    },
    "企业直播": {
        "reply_template": (
            "企业做大型直播或发布会，核心风险从来不是推流端，而是下行并发卡顿和网络抖动。"
            "通常需要具备多 CDN 智能切流、无延迟 WebRTC 互动以及全流程应急兜底机制，"
            "建议在筹备阶段就把播放器首屏加载率和并发压力测好，别等开播了才救火。"
        ),
        "video_topic": "万人企业直播为什么总翻车？大厂避坑指南揭秘",
        "video_hook": "老板正在台上做年度发布，参会人数一多就开始卡顿？大型直播最容易忽略的几个风险点要提前验证！",
        "dm_opener": (
            "你好，看到你在了解企业直播与线上活动保障。大型活动最怕突发并发卡顿，我们这有份《企业级直播全流程筹备与防翻车技术清单》，"
            "涵盖推流、CDN 调度及应急降级策略，方便的话告诉我预计人数和形式，发你一份对标案例。"
        ),
        "case": "[待核实] 全球线上经销商大会与新品发布会案例，客户名称和数据需经批准后补充",
        "template": "《企业万人直播全流程筹备排期表与技术演练SOP.pdf》",
        "demo": "POLYV 超低延迟无感切流与万人互动控制台 Demo",
    },
    "私域直播": {
        "reply_template": (
            "做私域直播千万别照搬公域带货那套‘硬催单’模式。私域高转化的核心在于‘微信生态连通 + 裂变链路闭环’，"
            "比如结合企微免登打通、直播间互动数据回传 CRM，以及基于客户标签做定向通知推送。"
        ),
        "video_topic": "公域砸钱做直播越来越亏？聪明品牌都在转战私域直播的三大底层逻辑",
        "video_hook": "公域投流成本越来越高，直播一停人就流失？如果还没打通企微和私域直播闭环，客户很难沉淀下来！",
        "dm_opener": (
            "你好，看到你在了解私域直播运营与搭建。我们这边整理了一套《品牌私域直播高转化运营与打法SOP》，"
            "包含企微互通、分销裂变与用户画像标签沉淀链路。方便的话告诉我你目前的用户沉淀场景，发你一份参考。"
        ),
        "case": "[待核实] 企微与私域直播协同案例，客户名称和转化数据需经批准后补充",
        "template": "《私域直播运营全流程策划表与转化节点拆解.pdf》",
        "demo": "POLYV 私域直播企微协同与带货互动控制台 Demo",
    },
    "视频点播": {
        "reply_template": (
            "企业自建视频点播，最大的坑在于视频转码适配慢、跨端播放卡顿以及无防盗链裸跑。"
            "企业级点播通常需要全终端自适应码率、全球 CDN 加速节点，配合防盗链签名机制，"
            "才能更好保障内训或付费视频在大规模员工或学员高频点播时稳定播放。"
        ),
        "video_topic": "企业做视频点播系统，别忽略这3个常见的播放器和转码坑",
        "video_hook": "员工抱怨看内训视频转圈卡顿，外包团队又建议大幅重构？先检查播放器和转码调度！",
        "dm_opener": (
            "你好，看到你在考虑企业视频点播与音视频托管方案。我们这边有份《企业级私有化视频点播选型与避坑指引》，"
            "涵盖自适应切片、防盗链及多端集成架构。方便的话告诉我你们的大概视频量和并发情况，发你一份对标方案。"
        ),
        "case": "[待核实] 大规模视频课件点播与分发案例，客户名称和数据需经批准后补充",
        "template": "《企业视频点播系统选型评估雷达图.pdf》",
        "demo": "POLYV 超清自适应视频点播播放器与智能转码后台体验",
    },
    "视频安全": {
        "reply_template": (
            "防盗录单靠禁用右键或普通加密码完全防不住录屏和抓包。"
            "真正能起到法律震慑和溯源作用的是‘跑马灯动态防伪水印（带员工工号/手机号）+ 视频切片动态加密’，"
            "即使被手机对着屏幕录，也能根据隐形或显性水印精准定位到泄露源头，从源头止损。"
        ),
        "video_topic": "内部高密培训课被倒卖？3招彻底封死企业课程盗录",
        "video_hook": "刚研发的核心课件被低价倒卖？别再只用普通网盘存放高密视频了！",
        "dm_opener": (
            "你好，看到你在关注课程防录屏防泄露。很多机构和企业被盗录往往是因为加密层级不够，"
            "我们整理过一份《企业高密视频防录屏与版权溯源技术白皮书》，如果你手头有高价值课程需要防护，随时发你一份行业成熟解法。"
        ),
        "case": "[待核实] 高密版权课程防盗防录案例，客户名称和数据需经批准后补充",
        "template": "《企业知识资产防盗录防护方案与法律存证指南.pdf》",
        "demo": "动态跑马灯水印与防抓包加密播放器在线体验",
    },
    "AI视频": {
        "reply_template": (
            "批量做视频或 PPT 转课件，如果单纯用普通剪辑软件效率太低。"
            "现在成熟工作流是将 PPT 课件直接导入，AI 自动根据排版提炼讲稿并驱动数字人讲解，"
            "10 分钟就能自动化出片，非常适合标准化产品手册和员工通识课程的快速量产。"
        ),
        "video_topic": "一个人如何批量做完50套员工内训课？PPT转AI微课全流程",
        "video_hook": "一个人如何批量完成员工课程？可以先把课件结构、讲稿和审核流程标准化！",
        "dm_opener": (
            "你好，看到你在研究 AI 课程与批量制作视频。我们做过很多将 PPT 一键批量生产为数字人视频的交付实践，"
            "有现成的《AI数字人课件量产效率工具包》，需要的话随时发你参考交流。"
        ),
        "case": "[待核实] AI数字人批量制作培训课程案例，客户名称和数据需经批准后补充",
        "template": "《PPT转视频与AI数字人微课制作操作手册.pdf》",
        "demo": "一键上传 PPT 生成 AI 讲师视频体验",
    },
    "技术集成": {
        "reply_template": (
            "自建直播服务往往面临维护成本高、WebRTC 和播放器多端适配难的挑战。"
            "采用低耦合 SDK/API 接入是主流选择，几行代码就能把直播间、聊天室和数据统计嵌入原生 APP 或 Web 系统中，"
            "工期从几个月缩短到几天，稳定性也由专业基础设施兜底。"
        ),
        "video_topic": "APP快速接入直播有多难？自建 vs SDK接入深度对比",
        "video_hook": "老板要求短周期在自有 APP 里接入大型直播？先评估自建和 SDK 接入的边界！",
        "dm_opener": (
            "你好，看到你在探讨直播 SDK 与技术接入。我们有完整的 iOS/Android/Web/小程序全端 SDK 示例工程和快速集成文档，"
            "可以发你一份技术集成包和沙箱环境先做个快速评估。"
        ),
        "case": "[待核实] SDK集成互动直播案例，客户名称和数据需经批准后补充",
        "template": "《企业直播 SDK 选型对比与 API 集成开发指引.pdf》",
        "demo": "全端直播与 WebRTC 互动 SDK 快速体验工程",
    },
    "出海": {
        "reply_template": (
            "出海跨国直播最容易卡在跨国跨运营商链路抖动和多语言字幕延迟上。"
            "核心是要有全球分布式节点智能调度覆盖，同时实时 AI 双语/多语字幕同传，"
            "保证海外不同地区的经销商和客户不仅看得顺畅，还能听懂核心业务宣讲。"
        ),
        "video_topic": "跨国海外发布会怎么做才不卡？全球企业直播核心要点",
        "video_hook": "海外客户刚进直播间就卡成 PPT？跨国直播如果不懂全球节点分发，投再多广告也是白费！",
        "dm_opener": (
            "你好，看到你在关注出海与全球直播。我们专门针对跨国发布会整理过《全球企业出海多语言直播实操方案》，"
            "附带了东南亚、中东、欧美不同区域的链路保障实测数据，欢迎发你参考。"
        ),
        "case": "[待核实] 全球多语言直播案例，客户名称和数据需经批准后补充",
        "template": "《出海企业全球多语言直播排期与网络保障方案.pdf》",
        "demo": "全球多节点加速与实时 AI 多语字幕演示 Demo",
    },
}


def _safe_public_reply(lead: LeadEvidence) -> str:
    """Create a fact-bounded public reply for the automated queue.

    The richer knowledge base remains available for human review, but public
    replies must not turn unverified capabilities, cases, or metrics into
    claims about POLYV.
    """
    quote = lead.quote.strip().replace("\n", " ")[:80]
    category_guidance = {
        "企业培训": "先把培训对象、人数、内容权限、学习记录和交付时间列清，再比较平台的内容分发和管理方式",
        "企业直播": "先把活动时间、预计人数、观看对象、互动方式和应急安排列清，再比较平台方案",
        "私域直播": "先把触达渠道、观看权限、互动方式和数据承接要求列清，再比较平台是否匹配现有流程",
        "视频点播": "先把视频规模、观看范围、权限要求和终端场景列清，再确认托管、播放和集成方案",
        "视频安全": "先把观看权限、内容分发、下载限制和泄露追溯要求列清，再向平台确认具体安全能力",
        "AI视频": "先把课件来源、内容审核、产出数量和交付时间列清，再比较制作工具与视频平台的衔接方式",
        "技术集成": "先把已有系统、接入端、接口要求、并发预期和交付周期列清，再比较集成方案",
        "出海": "先把覆盖地区、语言、观看对象、活动时间和服务要求列清，再向平台确认可支持范围",
    }
    guidance = category_guidance.get(lead.category, "先把业务场景、人数、权限、交付时间和预算范围列清，再比较平台方案")
    return (
        f"看到你提到“{quote}”。这类需求建议{guidance}。"
        "POLYV 可以作为待比较的方案之一，具体能力、交付方式和报价需要结合实际场景确认。"
        "如果方便，可以补充活动时间、预计人数和最看重的要求，我再帮你整理一份选型核对清单。"
    )


def build_conversion_pack(lead: LeadEvidence) -> ConversionPack:
    category = lead.category if lead.category in KNOWLEDGE_BASE else "企业培训"
    kb = KNOWLEDGE_BASE[category]

    reply = _safe_public_reply(lead)

    return ConversionPack(
        reply_text=reply,
        video_topic=kb["video_topic"],
        video_hook=kb["video_hook"],
        dm_opener=kb["dm_opener"],
        recommended_materials={
            "case": kb["case"],
            "template": kb["template"],
            "demo": kb["demo"],
        },
    )
