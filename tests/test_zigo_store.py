import json
from pathlib import Path

from local_tools.polyv_radar.zigo_store import ZigoStore


def _content():
    return {
        "platform": "xhs",
        "content_id": "post-1",
        "title": "企微客户跟进",
        "text": "销售客户跟进场景",
        "url": "https://www.xiaohongshu.com/explore/post-1",
        "author": "企业账号",
        "author_id": "author-1",
        "author_url": "https://www.xiaohongshu.com/user/profile/author-1",
        "source_keyword": "企微 沉睡客户",
        "source_type": "post",
        "create_time": "2026-09-30T00:00:00+00:00",
    }


def _comment():
    return {
        "platform": "xhs",
        "comment_id": "comment-1",
        "content_id": "post-1",
        "text": "我们客户跟进不过来，有没有工具",
        "author": "买方用户",
        "author_id": "buyer-1",
        "author_url": "https://www.xiaohongshu.com/user/profile/buyer-1",
        "native_comment_id": "native-1",
        "source_keyword": "企微 沉睡客户",
        "source_type": "comment",
        "published_at_raw": "2026-09-29",
    }


def test_zigo_store_is_idempotent_and_keeps_product_domains_separate(tmp_path: Path):
    store = ZigoStore(tmp_path / "zigoai" / "radar.sqlite3")
    store.initialize()
    rows = [_content(), _comment()]
    screened = [{**_comment(), "candidate_id": "candidate-1", "product_domain": "sales_agent", "decision": "candidate_pending_verification", "rule_score": 4, "quote": _comment()["text"]}]

    first = store.ingest_run("run-1", "sales_agent", rows, screened)
    second = store.ingest_run("run-1", "sales_agent", rows, screened)
    store.ingest_run("run-2", "geo", [_content()], [])

    assert first["inserted_contents"] == 1
    assert first["inserted_comments"] == 1
    assert second["changed"] is False
    assert store.summary("sales_agent")["comments"] == 1
    assert store.summary("geo")["contents"] == 1
    assert store.summary("sales_agent")["candidates"] == 1
    assert store.summary("geo")["candidates"] == 0
    assert store.list_runs()[0]["run_id"] == "run-2"
    store.close()


def test_zigo_store_persists_check_payload(tmp_path: Path):
    store = ZigoStore(tmp_path / "radar.sqlite3")
    store.initialize()
    check = {"candidate_id": "candidate-1", "status": "verified", "matched_quote": "原话"}
    store.ingest_run("run-1", "geo", [], [], [check])
    row = store.connection.execute("SELECT payload FROM zigo_checks WHERE candidate_id = ?", ("candidate-1",)).fetchone()
    assert json.loads(row[0])["status"] == "verified"
    store.close()
