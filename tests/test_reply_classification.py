"""Reply provenance: peer-probe replies must not read like lead replies."""

from local_tools.polyv_radar.reply_classification import classify_reply_author


def test_peer_brands_are_classified_as_peer():
    assert classify_reply_author("小鹅通官方")[0] == "peer"
    # Rendered with spaces on Xiaohongshu.
    assert classify_reply_author("爱 问 云")[0] == "peer"
    assert classify_reply_author("创客匠人")[0] == "peer"
    assert classify_reply_author("伯索云学堂")[0] == "peer"


def test_own_accounts_are_processing_artifacts():
    assert classify_reply_author("小馨的ZigoAi")[0] == "artifact"
    assert classify_reply_author("Polyv的小幕")[0] == "artifact"
    assert classify_reply_author("bugbg")[0] == "artifact"


def test_regular_users_are_prospects():
    assert classify_reply_author("cc星")[0] == "prospect"
    assert classify_reply_author("地表最强饭灵根🌙 찐친")[0] == "prospect"
    assert classify_reply_author("是自由的风和我们")[0] == "prospect"


def test_empty_author_is_unknown():
    assert classify_reply_author("")[0] == "unknown"
    assert classify_reply_author(None)[0] == "unknown"
