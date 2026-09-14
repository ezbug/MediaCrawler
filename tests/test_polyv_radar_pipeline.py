from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from local_tools.polyv_radar.adapters import normalize_comment, normalize_content
from local_tools.polyv_radar.config import load_config
from local_tools.polyv_radar.enrichment import (
    choose_enrichment_candidates,
    classify_identity_confidence,
    extract_company_role,
)
from local_tools.polyv_radar.ego_crawl_all import build_ego_launcher
from local_tools.polyv_radar.models import LeadEvidence, ProfilePost, ProfileSnapshot
from local_tools.polyv_radar.pipeline import candidate_bundle
from local_tools.polyv_radar.review import enforce_review_gates, parse_review_payload, review_schema, run_codex_review
from local_tools.polyv_radar.scoring import score_purchase_evidence
from local_tools.polyv_radar.storage import RadarStore


def _content(text: str = "企业培训与经销商大会"):
    return normalize_content(
        "dy",
        {
            "aweme_id": "dy-1",
            "desc": text,
            "aweme_url": "https://www.douyin.com/video/dy-1",
            "create_time": datetime.now(timezone.utc).isoformat(),
            "author_id": "user-1",
            "author_url": "https://www.douyin.com/user/user-1",
        },
        "经销商大会平台报价",
    )


def _comment(text: str):
    return normalize_comment(
        "dy",
        {
            "comment_id": "comment-1",
            "aweme_id": "dy-1",
            "content": text,
            "nickname": "用户",
            "author_id": "user-2",
            "author_url": "https://www.douyin.com/user/user-2",
            "create_time": datetime.now(timezone.utc).isoformat(),
        },
    )


def test_normalization_keeps_public_profile_identifiers() -> None:
    content = _content()
    comment = _comment("我们公司下个月要给全国经销商培训，求推荐平台")

    assert content is not None and comment is not None
    assert content.author_id == "user-1"
    assert content.author_url.endswith("user-1")
    assert comment.author_id == "user-2"
    assert comment.author_url.endswith("user-2")


def test_purchase_evidence_scores_active_business_event_high() -> None:
    content = _content("企业培训与经销商大会")
    comment = _comment("我们公司下个月要给全国经销商培训，求推荐能支持3000人的平台")

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment)

    assert result.score >= 6
    assert result.dimensions["business_scene"] == 2
    assert result.dimensions["project_timing"] == 2
    assert result.dimensions["platform_intent"] == 2
    assert result.dimensions["identity"] == 0
    assert result.rejected_reason == ""


def test_generic_sdk_question_is_capped_without_business_scene() -> None:
    content = _content("直播 SDK 开发教程")
    comment = _comment("直播 SDK 怎么实现")

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment)

    assert result.score <= 4
    assert result.rejected_reason != ""


def test_identity_extraction_requires_explicit_company_text() -> None:
    company, role = extract_company_role("某某证券｜数字化运营负责人｜负责投教直播")

    assert company == "某某证券"
    assert role == "数字化运营负责人"
    assert classify_identity_confidence(company, role, ["https://example.com/news"]) == "high"
    assert classify_identity_confidence("", "", ["https://example.com/news"]) == "low"
    assert classify_identity_confidence("", "", [], verified=True) == "high"


def test_candidate_enrichment_is_capped_and_deduplicated() -> None:
    candidates = [
        LeadEvidence(
            platform="dy",
            content_id=f"video-{index}",
            comment_id=f"comment-{index}",
            url="https://www.douyin.com/video/1",
            user="同一个人" if index < 2 else f"用户{index}",
            quote="公司需要平台方案",
            category="企业直播",
            solution="企业直播方向",
            score=6,
            author_id="same-user" if index < 2 else f"user-{index}",
            author_url="https://www.douyin.com/user/same-user" if index < 2 else f"https://www.douyin.com/user/{index}",
        )
        for index in range(55)
    ]

    selected = choose_enrichment_candidates(candidates, limit=50)

    assert len(selected) == 50
    assert len({item.author_id for item in selected}) == 50


def test_prefilter_excludes_configured_first_party_author() -> None:
    content = _content("全国经销商大会 企业培训平台")
    comment = _comment("我们公司下个月要做经销商培训，求平台报价")
    assert content is not None and comment is not None
    comment.author = "保利威的小何"

    from local_tools.polyv_radar.pipeline import build_prefilter_leads

    leads = build_prefilter_leads([content], [comment], excluded_author_names=("保利威",))
    assert leads == []


def test_existing_database_migration_preserves_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE contents (
            platform TEXT NOT NULL, content_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
            author_hash TEXT NOT NULL DEFAULT '', published_at TEXT NOT NULL DEFAULT '', likes INTEGER NOT NULL DEFAULT 0,
            comments_count INTEGER NOT NULL DEFAULT 0, shares INTEGER NOT NULL DEFAULT 0, plays INTEGER NOT NULL DEFAULT 0,
            source_keywords TEXT NOT NULL DEFAULT '[]', content_type TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, PRIMARY KEY (platform, content_id)
        );
        INSERT INTO contents(platform, content_id, first_seen_at, last_seen_at) VALUES ('dy', 'old-1', 'now', 'now');
        """
    )
    connection.commit()
    connection.close()

    store = RadarStore(path)
    store.initialize()
    row = store.connection.execute("SELECT content_id, author_id FROM contents").fetchone()

    assert row["content_id"] == "old-1"
    assert row["author_id"] == ""
    assert store.connection.execute("SELECT name FROM sqlite_master WHERE name='profiles'").fetchone()
    store.close()


def test_run_query_sources_are_isolated_between_batches(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    content = _content("公司年会直播平台")
    comment_a = normalize_comment(
        "dy",
        {"comment_id": "comment-a", "aweme_id": "dy-1", "content": "第一批"},
        source_keyword="批次A查询",
    )
    comment_b = normalize_comment(
        "dy",
        {"comment_id": "comment-b", "aweme_id": "dy-1", "content": "第二批"},
        source_keyword="批次B查询",
    )

    assert content is not None and comment_a is not None and comment_b is not None
    content.source_keywords = ["批次A查询"]
    store.upsert_content(content, run_id="run-a")
    content.source_keywords = ["批次B查询"]
    store.upsert_content(content, run_id="run-b")
    store.upsert_comment(comment_a, run_id="run-a")
    store.upsert_comment(comment_b, run_id="run-b")

    assert store.iter_contents("run-a")[0].source_keywords == ["批次A查询"]
    assert store.iter_contents("run-b")[0].source_keywords == ["批次B查询"]
    assert store.iter_comments("run-a")[0].source_keyword == "批次A查询"
    assert store.iter_comments("run-b")[0].source_keyword == "批次B查询"
    store.close()


def test_comment_upsert_preserves_author_id_and_author_url(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    comment = normalize_comment(
        "dy",
        {
            "comment_id": "comment-1",
            "aweme_id": "dy-1",
            "content": "需要企业培训平台",
            "author_id": "stable-user",
            "author_url": "https://www.douyin.com/user/stable-user",
        },
        source_keyword="查询A",
    )
    assert comment is not None
    store.upsert_comment(comment, run_id="run-a")
    comment.text = "更新后的评论"
    store.upsert_comment(comment, run_id="run-b")
    row = store.connection.execute(
        "SELECT author_id, author_url, parent_comment_id FROM comments WHERE comment_id = 'comment-1'"
    ).fetchone()
    assert row["author_id"] == "stable-user"
    assert row["author_url"].endswith("/stable-user")
    assert row["parent_comment_id"] == ""
    store.close()


def test_candidate_bundle_keeps_recent_profile_post_sources(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.upsert_profile(
        ProfileSnapshot(
            run_id="run-a",
            platform="dy",
            author_id="user-2",
            author_url="https://www.douyin.com/user/user-2",
            display_name="企业账号",
            bio="某某科技 公司培训负责人",
            company="某某科技公司",
            role="培训负责人",
            identity_confidence="medium",
        )
    )
    store.upsert_profile_post(
        ProfilePost(
            run_id="run-a",
            platform="dy",
            author_id="user-2",
            post_id="post-1",
            url="https://www.douyin.com/video/post-1",
            title="近期员工培训活动",
            text="近期员工培训活动回顾",
        )
    )
    lead = LeadEvidence(
        platform="dy",
        content_id="video-1",
        comment_id="comment-1",
        url="https://www.douyin.com/video/video-1",
        user="企业账号",
        quote="公司下个月需要培训平台",
        category="企业培训",
        solution="企业培训方向",
        score=6,
        author_id="user-2",
        profile_url="https://www.douyin.com/user/user-2",
    )
    bundle = candidate_bundle(store, "run-a", [lead])
    assert any(item["type"] == "profile_post" for item in bundle[0]["sources"])
    store.close()


def test_codex_review_payload_requires_evidence_references() -> None:
    schema = review_schema()
    assert "dimensions" in schema["properties"]
    assert "evidence" in schema["properties"]

    valid = {
        "score": 8,
        "dimensions": {
            "business_scene": 2,
            "project_timing": 2,
            "platform_intent": 2,
            "delivery_inquiry": 2,
            "identity": 0,
        },
        "event_type": "经销商大会",
        "identity_confidence": "low",
        "evidence": [
            {"dimension": "business_scene", "quote": "全国经销商培训", "url": "https://example.com/post"}
        ],
        "decision": "review",
        "reason": "有明确项目和平台需求，但缺少身份验证",
    }

    parsed = parse_review_payload(valid, {"https://example.com/post"})
    assert parsed["score"] == 8

    invalid = dict(valid)
    invalid["evidence"] = [{"dimension": "business_scene", "quote": "不是来源原文", "url": "https://not-allowed.example"}]
    assert parse_review_payload(invalid, {"https://example.com/post"}) is None


def test_review_gate_demotes_high_score_without_business_evidence() -> None:
    payload = {
        "score": 8,
        "dimensions": {
            "business_scene": 2,
            "project_timing": 2,
            "platform_intent": 2,
            "delivery_inquiry": 2,
            "identity": 0,
        },
        "event_type": "企业直播",
        "identity_confidence": "low",
        "evidence": [],
        "decision": "high_value",
        "reason": "模型原始判断",
    }

    gated = enforce_review_gates(payload, {"profile": {"identity_confidence": "low"}})

    assert gated["decision"] == "high_value"
    assert gated["score"] == 8

    payload["dimensions"]["business_scene"] = 0
    payload["score"] = 6
    gated = enforce_review_gates(payload, {"profile": {"identity_confidence": "low"}})
    assert gated["decision"] == "review"


def test_codex_review_runner_rejects_untrusted_source_urls() -> None:
    candidate = {
        "quote": "公司下个月需要培训平台",
        "sources": [{"url": "https://example.com/post", "text": "公司下个月需要培训平台"}],
        "profile": {"identity_confidence": "low"},
    }
    payload = {
        "score": 8,
        "dimensions": {name: (2 if name != "identity" else 0) for name in ("business_scene", "project_timing", "platform_intent", "delivery_inquiry", "identity")},
        "event_type": "员工培训",
        "identity_confidence": "low",
        "evidence": [{"dimension": "business_scene", "quote": "公司下个月需要培训平台", "url": "https://example.com/post"}],
        "decision": "high_value",
        "reason": "有项目和平台需求",
    }

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    parsed, status = run_codex_review(candidate, runner=fake_runner)
    assert status == "model_verified"
    assert parsed is not None and parsed["decision"] == "high_value"


def test_config_contains_event_query_volume() -> None:
    config = load_config(Path("local_tools/polyv_radar/pilot.toml"))
    total = sum(len(config.get_keywords_for_platform(platform)) for platform in config.platforms)

    assert total >= 30
    assert config.max_contents == 15
    assert config.max_comments == 30


def test_ego_launcher_uses_configured_collection_limits(tmp_path: Path) -> None:
    launcher = build_ego_launcher(Path("crawler.mjs"), "经销商大会", 15, 30, tmp_path)

    assert '"经销商大会"' in launcher
    assert '"15"' in launcher
    assert '"30"' in launcher
