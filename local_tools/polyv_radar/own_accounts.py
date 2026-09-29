"""Our own account display name per platform.

`auto_reply.mjs` verifies a send by checking that the comment container's author
text *contains* the value passed as ``--own-account`` (``containerAuthor.includes``).
So the value must be the **display name as the platform renders it on our own
comment**, not a handle and not a URL slug.

How each value was obtained (2026-09-29, read-only, from the signed-in browser):

| platform | value | source |
|---|---|---|
| zhihu | `bugbg` | header node labelled 点击打开bugbg的主页 — **and confirmed against a real published comment** |
| xhs | `小馨的创意工坊OvO` | our own profile page title + `.user-name` |
| dy | `Polyv的小幕` | `/user/self` title `Polyv的小幕的抖音` + avatar alt `Polyv的小幕头像` |
| bili | `小幕的创意工坊OvO` | `space.bilibili.com/350237651` space name |

Note xhs uses 小馨 while bili/dy use 小幕 — different characters, different
accounts. Do not "normalise" them; a wrong value silently makes
``own_account`` false.

Because the match is a substring check, a very short value would false-positive.
`is_distinctive` guards that.
"""

from __future__ import annotations

DISCOVERED_AT = "2026-09-29"

#: Minimum length for a substring match to be considered meaningful.
MIN_DISTINCTIVE_LEN = 4

OWN_ACCOUNTS: dict[str, str] = {
    "zhihu": "bugbg",
    "xhs": "小馨的创意工坊OvO",
    "dy": "Polyv的小幕",
    "bili": "小幕的创意工坊OvO",
}

#: Evidence for each value, so a future reader can re-check instead of trusting.
PROVENANCE: dict[str, str] = {
    "zhihu": "verified against a real published comment on zhuanlan.zhihu.com/p/2043648532419188153",
    "xhs": "our own profile page (user id 64e0f879000000000100cf2c)",
    "dy": "douyin.com/user/self title + avatar alt",
    "bili": "space.bilibili.com/350237651 space name",
}


def own_account(platform: str) -> str:
    """Display name for ``platform``; raises KeyError for an unknown platform."""
    key = str(platform or "").strip().lower()
    if key not in OWN_ACCOUNTS:
        raise KeyError(
            f"no own-account recorded for platform {platform!r}; "
            f"known: {sorted(OWN_ACCOUNTS)} — discover it with the ego-browser "
            f"own-profile page rather than guessing"
        )
    return OWN_ACCOUNTS[key]


def is_distinctive(value: str) -> bool:
    """True when a substring match on ``value`` is unlikely to false-positive."""
    return len(str(value or "").strip()) >= MIN_DISTINCTIVE_LEN


def reply_args(platform: str) -> list[str]:
    """``['--own-account', name]`` ready to splice into an auto_reply invocation.

    Returns ``[]`` when the platform is unknown, so a caller degrades to "not
    checked" (``own_account: null``) instead of passing a wrong name and
    recording a false negative.
    """
    try:
        name = own_account(platform)
    except KeyError:
        return []
    return ["--own-account", name]
