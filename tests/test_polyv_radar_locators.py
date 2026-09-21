from __future__ import annotations

import sqlite3
from pathlib import Path

from local_tools.polyv_radar.adapters import normalize_comment
from local_tools.polyv_radar.locator import (
    VENDOR_EXCLUSION_REASON,
    is_deliverable_lead,
    lead_exclusion_reason,
    locate_comment,
    locator_url,
    locate_store,
    run_ego_locator,
    select_deliverable_leads,
)
from local_tools.polyv_radar.config import RadarConfig
from local_tools.polyv_radar.models import CommentRecord, LeadEvidence
from local_tools.polyv_radar.storage import RadarStore
from local_tools.polyv_radar.report import render_verified_leads
from local_tools.polyv_radar.hunt import _with_long_tail


def test_comment_normalization_preserves_native_locator_fields() -> None:
    comment = normalize_comment(
        "bili",
        {
            "comment_id": "internal-1",
            "native_comment_id": "rpid-1",
            "native_parent_id": "rpid-root",
            "comment_url": "https://www.bilibili.com/video/BV1abc/#replyrpid-1",
            "source_type": "reply",
            "content_id": "BV1abc",
            "text": "公司正在筹备发布会直播，求平台报价",
            "author": "测试用户",
            "published_at_raw": "2天前",
        },
    )

    assert comment is not None
    assert comment.native_comment_id == "rpid-1"
    assert comment.native_parent_id == "rpid-root"
    assert comment.comment_url.endswith("#replyrpid-1")
    assert comment.source_type == "reply"
    assert comment.published_at is None
    assert comment.published_at_raw == "2天前"


def test_synthetic_internal_comment_id_is_not_native_id() -> None:
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "video-1_cm_2_1234567890",
            "content_id": "video-1",
            "text": "求平台报价",
        },
    )

    assert comment is not None
    assert comment.comment_id == "video-1_cm_2_1234567890"
    assert comment.native_comment_id == ""


def test_locator_requires_one_author_and_quote_match() -> None:
    comments = [
        {"author": "甲", "text": "我们公司正在做线上培训"},
        {"author": "乙", "text": "我们公司正在做线上培训"},
    ]

    result = locate_comment(comments, author="乙", quote="我们公司正在做线上培训")

    assert result.status == "verified"
    assert result.index == 1
    assert result.method == "author_quote"


def test_locator_marks_duplicate_matches_ambiguous() -> None:
    comments = [
        {"author": "甲", "text": "求平台报价"},
        {"author": "甲", "text": "求平台报价"},
    ]

    result = locate_comment(comments, author="甲", quote="求平台报价")

    assert result.status == "ambiguous"


def test_locator_url_only_claims_direct_url_for_verified_native_link() -> None:
    direct = locator_url(
        "bili",
        "https://www.bilibili.com/video/BV1abc/",
        native_comment_id="rpid-1",
        comment_url="https://www.bilibili.com/video/BV1abc/#replyrpid-1",
        verified=True,
    )
    fallback = locator_url(
        "dy",
        "https://www.douyin.com/video/123",
        native_comment_id="",
        comment_url="",
        verified=False,
    )

    assert direct.url.endswith("#replyrpid-1")
    assert direct.method == "direct_url"
    assert fallback.url == "https://www.douyin.com/video/123"
    assert fallback.method == "author_quote"


def test_old_comments_table_gets_locator_columns_without_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "radar.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE comments (
            platform TEXT NOT NULL,
            comment_id TEXT NOT NULL,
            content_id TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            author_hash TEXT NOT NULL DEFAULT '',
            author_id TEXT NOT NULL DEFAULT '',
            author_url TEXT NOT NULL DEFAULT '',
            parent_comment_id TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            likes INTEGER NOT NULL DEFAULT 0,
            source_keyword TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (platform, comment_id)
        )"""
    )
    connection.execute(
        "INSERT INTO comments(platform, comment_id, content_id, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
        ("dy", "legacy-1", "video-1", "now", "now"),
    )
    connection.commit()
    connection.close()

    store = RadarStore(path)
    store.initialize()
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(comments)")}
    assert {"native_comment_id", "native_parent_id", "comment_url", "source_type", "published_at_raw"} <= columns
    assert store.count("comments") == 1
    assert store.count("comment_locators") == 0
    store.close()


def test_comment_record_defaults_to_comment_source() -> None:
    comment = CommentRecord(platform="dy", comment_id="c", content_id="v")

    assert comment.source_type == "comment"


def test_store_persists_batch_locator_result(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.save_comment_locator(
        {
            "run_id": "run-1",
            "platform": "dy",
            "content_id": "video-1",
            "comment_id": "comment-1",
            "source_type": "comment",
            "content_url": "https://www.douyin.com/video/video-1",
            "comment_url": "https://www.douyin.com/video/video-1",
            "locator_method": "author_quote",
            "status": "verified",
            "matched_author": "甲",
            "matched_quote": "求平台报价",
        }
    )

    rows = store.load_comment_locators("run-1")

    assert rows[0]["status"] == "verified"
    assert rows[0]["locator_method"] == "author_quote"
    store.close()


def test_ego_locator_runner_uses_ego_browser_only(tmp_path: Path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "locator-output.json").write_text(
            '{"results":[{"run_id":"run-1","platform":"dy","content_id":"video-1","comment_id":"comment-1","status":"verified","locator_method":"author_quote","locator_url":"https://www.douyin.com/video/video-1","matched_author":"甲","matched_quote":"求平台报价"}]}',
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    results, log = run_ego_locator(
        [{"run_id": "run-1", "platform": "dy", "content_id": "video-1", "comment_id": "comment-1"}],
        tmp_path,
        tmp_path,
        runner=fake_runner,
    )

    assert not log
    assert calls[0][0] == ["ego-browser", "nodejs"]
    assert results["run-1:dy:video-1:comment-1"]["status"] == "verified"


def test_ego_locator_runner_keeps_partial_results_on_process_failure(tmp_path: Path) -> None:
    def failed_runner(command, **kwargs):
        (tmp_path / "locator-output.json").write_text(
            '{"results":[{"run_id":"run-1","platform":"dy","content_id":"video-1",'
            '"comment_id":"comment-1","status":"not_found","reason":"页面中未找到对应作者和原话"}]}',
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "browser stopped"})()

    results, log = run_ego_locator(
        [
            {"run_id": "run-1", "platform": "dy", "content_id": "video-1", "comment_id": "comment-1"},
            {"run_id": "run-1", "platform": "dy", "content_id": "video-2", "comment_id": "comment-2"},
        ],
        tmp_path,
        tmp_path,
        runner=failed_runner,
    )

    assert "browser stopped" in log
    assert results["run-1:dy:video-1:comment-1"]["status"] == "not_found"
    assert results["run-1:dy:video-2:comment-2"]["status"] == "error"


def test_deliverable_leads_require_verified_locator_and_unique_user() -> None:
    def lead(index: int, author_id: str, status: str = "verified") -> LeadEvidence:
        return LeadEvidence(
            platform="dy",
            content_id=f"video-{index}",
            comment_id=f"comment-{index}",
            url=f"https://www.douyin.com/video/{index}",
            user=f"用户{index}",
            quote="我们公司正在找平台报价",
            category="企业直播",
            solution="企业直播方向",
            score=4,
            author_id=author_id,
            dimensions={"business_scene": 1, "project_timing": 1, "platform_intent": 0, "delivery_inquiry": 0, "identity": 0},
            locator_status=status,
            decision="review",
        )

    selected = select_deliverable_leads([lead(1, "same"), lead(2, "same"), lead(3, "other", "ambiguous")], 20)

    assert len(selected) == 1
    assert selected[0].author_id == "same"


def test_locate_store_writes_ego_result_back_to_the_same_lead(tmp_path: Path) -> None:
    config = RadarConfig(
        data_root=tmp_path / "radar-data",
        platforms=["dy"],
        keywords={"企业直播": "企业直播平台"},
    )
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    candidate = LeadEvidence(
        platform="dy",
        content_id="video-1",
        comment_id="comment-1",
        url="https://www.douyin.com/video/video-1",
        user="甲",
        quote="公司正在找平台报价",
        category="企业直播",
        solution="企业直播方向",
        score=4,
        dimensions={"business_scene": 1, "project_timing": 1, "platform_intent": 1, "delivery_inquiry": 1, "identity": 0},
        decision="review",
        author_id="author-1",
    )
    preserved = LeadEvidence(
        platform="dy",
        content_id="video-2",
        comment_id="comment-2",
        url="https://www.douyin.com/video/video-2",
        user="乙",
        quote="普通技术讨论",
        category="未分类",
        solution="视频云方向",
        score=0,
        decision="reject",
        locator_status="pending",
    )
    store.save_leads("run-1", [candidate, preserved])
    store.close()

    def fake_runner(command, **kwargs):
        output = config.data_root / "locators" / "run-1" / "locator-output.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            '{"results":[{"run_id":"run-1","platform":"dy","content_id":"video-1","comment_id":"comment-1",'
            '"status":"verified","locator_method":"author_quote","locator_url":"https://www.douyin.com/video/video-1",'
            '"matched_author":"甲","matched_quote":"公司正在找平台报价"}]}',
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = locate_store(config, tmp_path, "run-1", runner=fake_runner)

    assert result["verified"] == 1
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    saved = store.load_leads("run-1")
    updated = next(lead for lead in saved if lead.comment_id == "comment-1")
    assert updated.locator_status == "verified"
    assert updated.locator_method == "author_quote"
    assert any(lead.comment_id == "comment-2" and lead.decision == "reject" for lead in saved)
    assert store.load_comment_locators("run-1")[0]["status"] == "verified"
    store.close()


def test_verified_report_contains_mixed_locator_fields() -> None:
    lead = LeadEvidence(
        platform="bili",
        content_id="BV1abc",
        comment_id="internal-comment",
        url="https://www.bilibili.com/video/BV1abc/",
        user="甲",
        quote="公司下个月要做发布会直播，求平台报价",
        category="企业直播",
        solution="企业直播方向",
        score=6,
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 1, "delivery_inquiry": 1, "identity": 0},
        source_type="reply",
        native_comment_id="rpid-1",
        parent_comment_id="rpid-root",
        comment_url="https://www.bilibili.com/video/BV1abc/#replyrpid-1",
        locator_method="direct_url",
        locator_status="verified",
        locator_verified_at="2026-09-15T00:00:00+00:00",
        decision="review",
    )

    report = render_verified_leads("run-1", [lead])

    assert "评论定位URL" in report
    assert "#replyrpid-1" in report
    assert "rpid-root" in report
    assert "Ego验证状态" in report


def test_delivery_evidence_is_enough_for_a_four_point_candidate() -> None:
    lead = LeadEvidence(
        platform="dy",
        content_id="video-delivery",
        comment_id="comment-delivery",
        url="https://www.douyin.com/video/video-delivery",
        user="甲",
        quote="公司在找支持并发和交付的平台",
        category="企业直播",
        solution="企业直播方向",
        score=4,
        dimensions={"business_scene": 2, "project_timing": 0, "platform_intent": 0, "delivery_inquiry": 2, "identity": 0},
        locator_status="verified",
        decision="review",
    )

    assert select_deliverable_leads([lead], 20) == [lead]


def test_vendor_and_editorial_accounts_do_not_enter_delivery_list() -> None:
    lead = LeadEvidence(
        platform="zhihu",
        content_id="p-1",
        comment_id="",
        url="https://zhuanlan.zhihu.com/p/1",
        user="诺云直播",
        quote="2026企业年会直播攻略与平台推荐",
        content_title="2026企业年会直播攻略与平台推荐",
        category="企业直播",
        solution="企业直播方向",
        score=8,
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2, "delivery_inquiry": 1, "identity": 1},
        source_type="post",
        profile_bio="企业直播服务系统",
        locator_status="verified",
        decision="high_value",
    )

    assert not is_deliverable_lead(lead)


def test_profile_demand_post_is_not_vendor_filtered_by_its_own_quote() -> None:
    lead = LeadEvidence(
        platform="xhs",
        content_id="note-1",
        comment_id="",
        url="https://www.xiaohongshu.com/explore/note-1",
        user="红尘无味",
        quote="征集全流程年会直播供应商",
        content_title="征集全流程年会直播供应商",
        category="企业直播",
        solution="企业活动直播方向",
        profile_bio="红尘无味\n小红书号：490558472\n男士勿扰！！！\n31岁",
        score=8,
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2},
        locator_status="verified",
        source_type="content",
        author_id="author-1",
    )

    assert lead_exclusion_reason(lead) != VENDOR_EXCLUSION_REASON


def test_explicit_buyer_event_post_is_not_blocked_by_editorial_wording() -> None:
    lead = LeadEvidence(
        platform="zhihu",
        content_id="answer-3",
        comment_id="",
        url="https://www.zhihu.com/question/1/answer/3",
        user="企业用户",
        quote="公司年会要搞线上直播，有好的直播平台推荐吗？",
        content_title="公司年会要搞线上直播，有好的直播平台推荐吗？",
        category="企业直播",
        solution="企业活动直播方向",
        score=5,
        dimensions={"business_scene": 2, "project_timing": 1, "platform_intent": 2, "delivery_inquiry": 0, "identity": 0},
        source_type="answer",
        intent_class="buyer_request",
        locator_status="verified",
        decision="review",
    )

    assert lead_exclusion_reason(lead) == ""


def test_generic_zhihu_author_and_editorial_selection_article_do_not_enter_delivery_list() -> None:
    lead = LeadEvidence(
        platform="zhihu",
        content_id="p-2",
        comment_id="",
        url="https://zhuanlan.zhihu.com/p/2",
        user="知乎答主",
        quote="中小企业培训数字化选型，别再交智商税了",
        content_title="中小企业培训数字化选型，别再交智商税了",
        category="企业培训",
        solution="企业培训方向",
        score=7,
        dimensions={"business_scene": 2, "project_timing": 2, "platform_intent": 2, "delivery_inquiry": 0, "identity": 1},
        source_type="post",
        locator_status="verified",
        decision="high_value",
    )

    assert not is_deliverable_lead(lead)


def test_long_tail_wave_does_not_repeat_first_wave_queries() -> None:
    config = RadarConfig(
        data_root=Path("/tmp/polyv-radar-test"),
        platforms=["dy", "xhs", "bili", "zhihu"],
        keywords={"base": "base"},
        platform_keywords={"dy": {"base": "base"}},
    )

    expanded = _with_long_tail(config)

    assert sum(len(values) for values in expanded.platform_keywords.values()) == 16
    assert "base" not in expanded.platform_keywords.get("dy", {})
    assert any("我们公司" in keyword for keyword in expanded.platform_keywords["dy"].values())
    assert any("老板让我找" in keyword for keyword in expanded.platform_keywords["dy"].values())
    assert all(platform in expanded.platform_keywords for platform in config.platforms)
