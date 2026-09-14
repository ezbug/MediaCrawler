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
            "嵌入到企微或飞书里，带打卡和防录屏播放器。交付效率和完成率能提高好几倍。"
        ),
        "video_topic": "企业做内训最容易踩的3个坑：为什么发了资料根本没人学？",
        "video_hook": "花几万块买的培训课件，发到员工群里打开率不到 5%？很多管理者第一步就搞错了！",
        "dm_opener": (
            "你好，看到你在探讨企业培训落地的问题。我们这边沉淀了一套《企业微课与数字化培训落地方案SOP》，"
            "里面有同类规模企业如何把传统培训转为高打开率数字化内训的拆解。如果你正在优化内训，可以告诉我大概人数和场景，发你一份参考。"
        ),
        "case": "某头部零售/制造业 5000人线上培训与通关考核闭环实战",
        "template": "《企业数字化培训实施 SOP 与效果评估表.pdf》",
        "demo": "POLYV PPT 智能转微课 / 在线通关考核播放器体验",
    },
    "企业直播": {
        "reply_template": (
            "万人以上的大型线上活动或发布会，核心风险从来不是推流端，而是下行并发卡顿和网络抖动。"
            "通常需要具备多 CDN 智能切流、无延迟 WebRTC 互动以及全流程应急兜底机制，"
            "建议在筹备阶段就把播放器首屏加载率和并发压力测好，别等开播了才救火。"
        ),
        "video_topic": "万人企业直播为什么总翻车？大厂避坑指南揭秘",
        "video_hook": "老板正在台上做年度发布，台下 5000 个员工全在刷屏喊卡顿？万人直播最致命的几个死穴你必须知道！",
        "dm_opener": (
            "你好，看到你在了解大型直播与线上活动保障。大型活动最怕突发并发卡顿，我们这有份《万人企业直播全流程筹备与防翻车技术清单》，"
            "涵盖推流、CDN 调度及应急降级策略，方便的话告诉我预计人数和形式，发你一份对标案例。"
        ),
        "case": "某世界500强全球线上经销商大会与新品发布会万人直播保障",
        "template": "《企业万人直播全流程筹备排期表与技术演练SOP.pdf》",
        "demo": "POLYV 超低延迟无感切流与万人互动控制台 Demo",
    },
    "视频安全": {
        "reply_template": (
            "防盗录单靠禁用右键或普通加密码完全防不住录屏和抓包。"
            "真正能起到法律震慑和溯源作用的是‘跑马灯动态防伪水印（带员工工号/手机号）+ 视频切片动态加密’，"
            "即使被手机对着屏幕录，也能根据隐形或显性水印精准定位到泄露源头，从源头止损。"
        ),
        "video_topic": "内部高密培训课被倒卖？3招彻底封死企业课程盗录",
        "video_hook": "刚研发的独家核心课件，第二天就在某鱼某宝被 9 块 9 倒卖？别再用普通网盘存高密视频了！",
        "dm_opener": (
            "你好，看到你在关注课程防录屏防泄露。很多机构和企业被盗录往往是因为加密层级不够，"
            "我们整理过一份《企业高密视频防录屏与版权溯源技术白皮书》，如果你手头有高价值课程需要防护，随时发你一份行业成熟解法。"
        ),
        "case": "头部职业教育机构 10 万+小时核心高密版权课程防盗防录实战",
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
        "video_hook": "一个人做完 50 门课程要多久？以前要一个月，现在用这套 AI 工作流只要一天！",
        "dm_opener": (
            "你好，看到你在研究 AI 课程与批量制作视频。我们做过很多将 PPT 一键批量生产为数字人视频的交付实践，"
            "有现成的《AI数字人课件量产效率工具包》，需要的话随时发你参考交流。"
        ),
        "case": "某金融机构利用 AI 数字人 3 天完成 200 门全员合规培训课制作",
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
        "video_hook": "老板让两个星期在自有 APP 里接好万人直播？千万别傻傻从底层自建！",
        "dm_opener": (
            "你好，看到你在探讨直播 SDK 与技术接入。我们有完整的 iOS/Android/Web/小程序全端 SDK 示例工程和快速集成文档，"
            "可以发你一份技术集成包和沙箱环境先做个快速评估。"
        ),
        "case": "某知名协同办公平台通过 SDK 快速上线万人级互动直播模块",
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
        "case": "中国出海品牌全球新品发布会跨 15 国同屏直播保障",
        "template": "《出海企业全球多语言直播排期与网络保障方案.pdf》",
        "demo": "全球多节点加速与实时 AI 多语字幕演示 Demo",
    },
}


def build_conversion_pack(lead: LeadEvidence) -> ConversionPack:
    category = lead.category if lead.category in KNOWLEDGE_BASE else "企业培训"
    kb = KNOWLEDGE_BASE[category]

    # Personalize reply
    quote_snippet = lead.quote.strip().replace("\n", " ")[:40]
    reply = f"针对你提到的“{quote_snippet}...”的情况，{kb['reply_template']}"

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
