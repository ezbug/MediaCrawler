from local_tools.polyv_radar.comment_style import (
    choose_mode,
    comment_reply,
    first_line_chars,
    reactivation_comment,
)


def test_comment_reply_starts_with_short_native_opener() -> None:
    text = comment_reply("我们公司客户一直不回消息怎么办？", "企业培训")
    assert text == "先看培训流程"
    assert first_line_chars(text) <= 10
    assert "POLYV" not in text


def test_reaction_mode_is_used_for_non_question_pain_points() -> None:
    quote = "客户不回有一万个理由"
    assert choose_mode(quote) == "reaction"
    text = comment_reply(quote, "企业培训")
    assert text == "我也遇到过，解决没？"
    assert first_line_chars(text) <= 10
    assert "POLYV" not in text


def test_price_question_uses_solve_mode_without_brand() -> None:
    assert choose_mode("这个系统怎么收费，什么价格") == "solve"
    text = comment_reply("这个系统怎么收费，什么价格", "技术集成")
    assert text == "先看接入方案"
    assert "POLYV" not in text
    assert first_line_chars(text) <= 10


def test_historical_reply_is_one_short_question_without_brand() -> None:
    text = reactivation_comment("北京海淀60人报价", "企业活动")
    assert text == "现在还要做吗？"
    assert "POLYV" not in text
    assert first_line_chars(text) <= 10
