"""Our own-account display names per platform.

A wrong value here silently turns a real send into ``own_account: false``, so the
mapping is pinned and its hazards are tested.
"""

from __future__ import annotations

import pytest

from local_tools.polyv_radar.own_accounts import (
    MIN_DISTINCTIVE_LEN,
    OWN_ACCOUNTS,
    PROVENANCE,
    is_distinctive,
    own_account,
    reply_args,
)

PLATFORMS = ("zhihu", "xhs", "dy", "bili")


def test_every_platform_the_sender_supports_is_covered() -> None:
    # auto_reply.mjs accepts exactly these four platform codes
    assert set(OWN_ACCOUNTS) == set(PLATFORMS)


def test_every_value_has_provenance() -> None:
    for platform in PLATFORMS:
        assert PROVENANCE.get(platform), f"{platform} has no recorded evidence"


def test_values_are_distinctive_enough_for_a_substring_match() -> None:
    """The sender matches with `containerAuthor.includes(ownName)`.

    A short value (e.g. "小幕") could match an unrelated commenter's name, so the
    recorded names must be long enough to be specific.
    """
    for platform in PLATFORMS:
        value = OWN_ACCOUNTS[platform]
        assert is_distinctive(value), f"{platform} value {value!r} is too short to be safe"
        assert len(value) >= MIN_DISTINCTIVE_LEN


def test_zhihu_value_is_the_verified_one() -> None:
    """This one was confirmed against a real published comment, not just a header."""
    assert own_account("zhihu") == "bugbg"


def test_xhs_and_bili_names_match_the_reverified_display_values() -> None:
    """Re-read 2026-10-08 from our own published replies.

    The accounts were rebranded to ZigoAI between 2026-09-29 (when the names were
    first recorded) and 2026-10-08, so the old values would now make a genuine
    send verify as ``own_account: false``.
    """
    assert own_account("xhs") == "小馨的ZigoAi"
    assert own_account("bili") == "ZigoAi的小慕"
    assert own_account("xhs") != own_account("bili")


def test_platform_lookup_is_case_and_whitespace_tolerant() -> None:
    assert own_account(" ZHIHU ") == own_account("zhihu")


def test_unknown_platform_raises_instead_of_returning_a_guess() -> None:
    with pytest.raises(KeyError) as excinfo:
        own_account("weibo")
    assert "no own-account recorded" in str(excinfo.value)


def test_reply_args_splices_the_flag() -> None:
    args = reply_args("zhihu")
    assert args == ["--own-account", "bugbg"]


def test_reply_args_degrades_to_empty_for_an_unknown_platform() -> None:
    """Better to record 'not checked' (null) than to pass a wrong name."""
    assert reply_args("weibo") == []
