from local_tools.polyv_radar.conversion_engine import build_conversion_pack
from local_tools.polyv_radar.follow_up_style import build_follow_up_reply
from local_tools.polyv_radar.models import LeadEvidence


def _lead(category: str) -> LeadEvidence:
    return LeadEvidence(
        platform="dy",
        content_id="video-1",
        comment_id="comment-1",
        url="https://www.douyin.com/video/video-1",
        user="用户",
        quote="我们公司客户一直不回消息怎么办？",
        category=category,
        solution="企业培训",
        score=6,
        source_type="comment",
    )


def test_follow_up_reply_uses_structured_second_response() -> None:
    text = build_follow_up_reply("我们已经在做，但跟进还是乱", "企业培训")
    assert text == "先看内容和学习记录，我帮你对方案"
    assert len(text) <= 20
    assert "主管" not in text
    assert "内部确认" not in text


def test_follow_up_reply_supports_zigo_sales_without_polyv_claims() -> None:
    text = build_follow_up_reply("客户回了但后来就没消息了", domain="zigo_sales", brand="ZigoAI")
    assert text == "先看首响和线索分层，我帮你对方案"
    assert "POLYV" not in text


def test_conversion_pack_exposes_private_follow_up_template() -> None:
    pack = build_conversion_pack(_lead("企业培训"))
    assert pack.dm_follow_up
    assert pack.dm_follow_up == "先看内容和学习记录，我帮你对方案"
