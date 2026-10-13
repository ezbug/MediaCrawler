import pytest

from local_tools.polyv_radar.comment_style import (
    category_comment_guidance,
    choose_mode,
    comment_reply,
    first_line_chars,
    reactivation_comment,
)


def test_comment_reply_praises_question_first() -> None:
    text = comment_reply("我们公司客户一直不回消息怎么办？", "企业培训")
    assert text == "问得好，后来怎么解决的？"
    assert first_line_chars(text) <= 15
    assert "POLYV" not in text


def test_reaction_mode_praises_experience_and_asks_back() -> None:
    quote = "客户不回有一万个理由"
    assert choose_mode(quote) == "reaction"
    text = comment_reply(quote, "企业培训")
    assert text == "说得太真实了，后来顺利吗？"
    assert "同行" not in text
    assert first_line_chars(text) <= 15
    assert "POLYV" not in text
    assert "解决没" not in text


def test_price_question_uses_praise_then_solve_probe() -> None:
    assert choose_mode("这个系统怎么收费，什么价格") == "solve"
    text = comment_reply("这个系统怎么收费，什么价格", "技术集成")
    assert text == "问得好，后来怎么解决的？"
    assert "POLYV" not in text
    assert first_line_chars(text) <= 15


def test_guidance_replaces_question_and_stays_short() -> None:
    text = comment_reply(
        "我们公司要搞员工培训，求推荐平台",
        "企业培训",
        guidance=category_comment_guidance("企业培训"),
    )
    assert text == "问得好，人数权限先理清"
    assert first_line_chars(text) <= 15
    assert "POLYV" not in text


def test_overlong_guidance_is_rejected() -> None:
    with pytest.raises(ValueError):
        comment_reply(
            "客户不回有一万个理由",
            "企业培训",
            guidance="这是一句远远超过十五个汉字限制的指导内容",
        )


def test_historical_reply_is_praise_first_and_short() -> None:
    text = reactivation_comment("北京海淀60人报价", "企业活动")
    assert text == "讲得在理，现在还有这问题吗？"
    assert "POLYV" not in text
    assert first_line_chars(text) <= 15


def test_industry_name_does_not_add_peer_wording() -> None:
    text = comment_reply("客户不回有一万个理由", "企业培训", industry="教育")
    assert text == "说得太真实了，后来顺利吗？"
    assert "同行" not in text
    assert first_line_chars(text) <= 15
    assert "POLYV" not in text


def test_sister_variant_is_praise_first_and_within_limit() -> None:
    text = comment_reply("客户不回有一万个理由", "企业培训", variant="sister")
    assert text == "说得太真实了，后来咋解决的啊姐妹"
    assert "POLYV" not in text
    assert first_line_chars(text) <= 15


def test_default_guidance_covers_unmapped_category() -> None:
    assert category_comment_guidance("未知类别") == "场景人数先理清"
    text = comment_reply("我们想做个活动", "未知类别", guidance=category_comment_guidance("未知类别"))
    assert first_line_chars(text) <= 15
