import re

from local_tools.polyv_radar.comment_style import (
    choose_mode,
    comment_reply,
    first_line_chars,
    reactivation_comment,
)


def test_comment_reply_starts_with_short_native_opener() -> None:
    text = comment_reply("我们公司客户一直不回消息怎么办？", "企业培训")
    opener = text.split("。", 1)[0]
    assert first_line_chars(opener) <= 10
    assert "我们公司客户一直不回消息怎么办？" in text
    assert "POLYV" in text


def test_reaction_mode_is_used_for_non_question_pain_points() -> None:
    quote = "客户不回有一万个理由"
    assert choose_mode(quote) == "reaction"
    text = comment_reply(quote, "企业培训")
    opener = re.split(r"[。！？!?]", text, 1)[0]
    assert first_line_chars(opener) <= 10
    assert "客户不回有一万个理由" in text


def test_price_question_uses_solve_mode_without_double_punctuation() -> None:
    assert choose_mode("这个系统怎么收费，什么价格") == "solve"
    text = comment_reply("这个系统怎么收费，什么价格", "技术集成")
    assert "？。" not in text
    assert first_line_chars(text.split("。", 1)[0]) <= 10


def test_historical_reply_starts_with_short_reactivation_question() -> None:
    text = reactivation_comment("北京海淀60人报价", "企业活动")
    assert text.startswith("现在这方面还有需求吗？")
    assert "POLYV" in text
    assert first_line_chars(text.split("？", 1)[0]) <= 10
