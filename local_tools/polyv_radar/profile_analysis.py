"""Internal-only profile inference for lead ranking and routing.

All demographic and trend fields are guesses with explicit confidence labels.
They must not be written into public replies or treated as verified facts.
"""

from __future__ import annotations

from typing import Iterable

INDUSTRY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("教育培训", ("教育", "培训", "讲师", "课程", "教师", "招生", "知识付费", "高校", "学校")),
    ("医疗健康", ("医疗", "医生", "医院", "健康", "医药", "诊所", "护理")),
    ("金融保险", ("金融", "保险", "证券", "银行", "投教", "基金")),
    ("汽车", ("汽车", "车行", "4S", "二手车", "新能源车")),
    ("外贸跨境", ("外贸", "跨境", "出海", "国际站", "WhatsApp", "询盘")),
    ("制造业", ("工厂", "制造", "机械", "设备", "模具", "生产", "供应链")),
    ("电商零售", ("电商", "淘宝", "抖音电商", "店铺", "零售", "带货")),
    ("IT软件", ("软件", "开发", "程序员", "SaaS", "架构", "技术", "AI", "产品经理")),
    ("企业服务", ("咨询", "企业服务", "人力资源", "猎头", "管理顾问")),
    ("会展活动", ("会展", "活动", "峰会", "发布会", "大赛", "展会")),
    ("房产家居", ("房产", "地产", "家居", "装修", "建材")),
    ("传媒内容", ("传媒", "自媒体", "短视频", "直播", "内容", "博主")),
)

_FEMALE_TERMS = ("宝妈", "妈妈", "孕妈", "女士", "小姐姐", "姐姐")
_MALE_TERMS = ("爸爸", "先生", "老哥", "兄弟", "男士")
_YOUNG_TERMS = ("游戏", "二次元", "动漫", "潮玩", "手办", "学生", "大学生", "应届", "00后", "95后", "副业")
_OLDER_TERMS = ("退休", "养生", "中老年", "60后", "70后", "带孙", "广场舞", "棋牌", "茶文化")
_MODERN_TERMS = ("AI", "ai", "短视频", "直播", "自媒体", "出海", "数字化", "数据", "私域", "自动化")
_TRADITIONAL_TERMS = ("传统行业", "线下门店", "纸质", "电话销售", "老方法", "纯人工")


def _combined_text(display_name: str, bio: str, posts: Iterable[dict]) -> str:
    chunks = [str(display_name or ""), str(bio or "")]
    for post in posts or ():
        if isinstance(post, dict):
            chunks.append(str(post.get("title") or ""))
            chunks.append(str(post.get("text") or ""))
    return " ".join(chunks).strip()


def _hits(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if term and term in text]


def analyze_profile(
    *,
    display_name: str = "",
    bio: str = "",
    posts: Iterable[dict] | None = None,
    verified: bool = False,
    company: str = "",
    role: str = "",
) -> dict:
    """Return internal-only profile guesses with confidence labels."""
    text = _combined_text(display_name, bio, posts or ())
    evidence: list[str] = []

    industry = "unknown"
    industry_confidence = "unknown"
    for name, terms in INDUSTRY_RULES:
        matched = _hits(text, terms)
        if matched:
            industry = name
            industry_confidence = "medium" if len(matched) >= 2 else "low"
            evidence.append(f"行业线索: {', '.join(matched[:4])}")
            break

    female_hits = _hits(text, _FEMALE_TERMS)
    male_hits = _hits(text, _MALE_TERMS)
    if female_hits and not male_hits:
        gender_guess, gender_confidence = "female", "low"
        evidence.append(f"性别线索: {', '.join(female_hits[:3])}")
    elif male_hits and not female_hits:
        gender_guess, gender_confidence = "male", "low"
        evidence.append(f"性别线索: {', '.join(male_hits[:3])}")
    else:
        gender_guess, gender_confidence = "unknown", "unknown"

    young_hits = _hits(text, _YOUNG_TERMS)
    older_hits = _hits(text, _OLDER_TERMS)
    if young_hits and not older_hits:
        age_band_guess, age_confidence = "young", "low"
        evidence.append(f"年轻线索: {', '.join(young_hits[:3])}")
    elif older_hits and not young_hits:
        age_band_guess, age_confidence = "older", "low"
        evidence.append(f"年长线索: {', '.join(older_hits[:3])}")
    else:
        age_band_guess, age_confidence = "unknown", "unknown"

    modern_hits = _hits(text, _MODERN_TERMS)
    traditional_hits = _hits(text, _TRADITIONAL_TERMS)
    if modern_hits and not traditional_hits:
        trend_alignment, trend_confidence = "modern", "low"
        evidence.append(f"潮流线索: {', '.join(modern_hits[:3])}")
    elif traditional_hits and not modern_hits:
        trend_alignment, trend_confidence = "traditional", "low"
        evidence.append(f"传统线索: {', '.join(traditional_hits[:3])}")
    else:
        trend_alignment, trend_confidence = "unknown", "unknown"

    company_name = str(company or "").strip()
    return {
        "industry": industry,
        "industry_confidence": industry_confidence,
        "gender_guess": gender_guess,
        "gender_confidence": gender_confidence,
        "company_exposed": bool(company_name),
        "company_name": company_name,
        "age_band_guess": age_band_guess,
        "age_confidence": age_confidence,
        "trend_alignment": trend_alignment,
        "trend_confidence": trend_confidence,
        "analysis_evidence": evidence,
        "analysis_notes": (
            "内部画像推测，仅供排序和路由；性别/年龄/公司名不得写入公开回复。"
            if verified else
            "内部画像推测，未认证；仅供排序和路由，不得当作事实或对外使用。"
        ),
    }
