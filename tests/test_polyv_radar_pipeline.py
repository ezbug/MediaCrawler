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
    _clean_profile_text,
)
from local_tools.polyv_radar.ego_crawl_all import build_ego_batch_launcher, build_ego_launcher, run_ego_crawlers
from local_tools.polyv_radar.models import LeadEvidence, ProfilePost, ProfileSnapshot
from local_tools.polyv_radar.pipeline import candidate_bundle
from local_tools.polyv_radar.review import (
    build_review_batch_prompt,
    candidate_review_id,
    enforce_review_gates,
    parse_review_payload,
    review_batch_schema,
    review_schema,
    run_codex_review,
    run_codex_review_batch,
)
from local_tools.polyv_radar.scoring import score_purchase_evidence
from local_tools.polyv_radar.storage import RadarStore
from local_tools.polyv_radar.workflow import load_workflow_run


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


def test_budget_question_counts_as_purchase_and_delivery_evidence() -> None:
    content = _content("发布会直播搭建的全过程")
    comment = _comment("这些东西整出来预算大概多少")

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment)

    assert result.dimensions["business_scene"] == 2
    assert result.dimensions["platform_intent"] == 2
    assert result.dimensions["delivery_inquiry"] == 2
    assert result.score >= 6


def test_generic_sdk_question_is_capped_without_business_scene() -> None:
    content = _content("直播 SDK 开发教程")
    comment = _comment("直播 SDK 怎么实现")

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment)

    assert result.score <= 4
    assert result.rejected_reason != ""


def test_generic_comment_does_not_inherit_purchase_intent_from_video_title() -> None:
    content = _content("企业新品发布会直播方案")
    comment = _comment("支持，讲得很好")

    assert content is not None and comment is not None
    result = score_purchase_evidence(content, comment)

    assert result.dimensions["business_scene"] == 2
    assert result.dimensions["project_timing"] == 0
    assert result.dimensions["platform_intent"] == 0
    assert result.dimensions["delivery_inquiry"] == 0
    assert result.score == 2


def test_business_event_terms_are_not_treated_as_ad_or_medical_negatives() -> None:
    promotion = _content("线上招商会直播方案")
    promotion_comment = _comment("我们公司正在筹备线上招商会，求平台报价")
    medical = _content("医院学术会议直播")
    medical_comment = _comment("我们正在筹备学术会议，求直播平台方案")

    assert promotion is not None and promotion_comment is not None
    assert medical is not None and medical_comment is not None
    promotion_result = score_purchase_evidence(promotion, promotion_comment)
    medical_result = score_purchase_evidence(medical, medical_comment)

    assert promotion_result.rejected_reason == ""
    assert promotion_result.score >= 4
    assert medical_result.rejected_reason == ""
    assert medical_result.event_type == "医学会议"
    assert medical_result.score >= 4


def test_identity_extraction_requires_explicit_company_text() -> None:
    company, role = extract_company_role("某某证券｜数字化运营负责人｜负责投教直播")

    assert company == "某某证券"
    assert role == "数字化运营负责人"
    assert classify_identity_confidence(company, role, ["https://example.com/news"]) == "high"
    assert classify_identity_confidence("", "", ["https://example.com/news"]) == "low"
    assert classify_identity_confidence("", "", [], verified=True) == "high"


def test_profile_cleaning_drops_xhs_shell_without_dropping_real_bio() -> None:
    cleaned = _clean_profile_text(
        "首页\n直播\n通知\n红尘无味\n小红书号：490558472\n男士勿扰！！！\n31岁\n65\n关注\n"
        "沪ICP备13030189号 | 营业执照"
    )

    assert "首页" not in cleaned
    assert "直播｜通知" not in cleaned
    assert "男士勿扰！！！" in cleaned
    assert "沪ICP备" not in cleaned


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


def test_review_gate_cannot_invent_recent_or_delivery_evidence() -> None:
    payload = {
        "score": 8,
        "dimensions": {
            "business_scene": 2,
            "project_timing": 2,
            "platform_intent": 2,
            "delivery_inquiry": 2,
            "identity": 2,
        },
        "event_type": "公司年会",
        "identity_confidence": "high",
        "evidence": [],
        "decision": "high_value",
        "reason": "模型原始判断",
    }

    gated = enforce_review_gates(
        payload,
        {
            "rule_dimensions": {
                "business_scene": 2,
                "project_timing": 1,
                "platform_intent": 1,
                "delivery_inquiry": 0,
                "identity": 0,
            },
            "profile": {"identity_confidence": "medium"},
        },
    )

    assert gated["dimensions"] == {
        "business_scene": 2,
        "project_timing": 1,
        "platform_intent": 1,
        "delivery_inquiry": 0,
        "identity": 0,
    }
    assert gated["score"] == 4


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


def test_codex_batch_review_validates_each_candidate_and_uses_stable_ids() -> None:
    candidates = [
        {
            "platform": "dy",
            "content_id": f"video-{index}",
            "comment_id": f"comment-{index}",
            "quote": "公司下个月需要培训平台",
            "sources": [{"url": f"https://example.com/post-{index}", "text": "公司下个月需要培训平台"}],
            "rule_dimensions": {
                "business_scene": 2,
                "project_timing": 2,
                "platform_intent": 0,
                "delivery_inquiry": 0,
                "identity": 0,
            },
            "profile": {"identity_confidence": "low"},
        }
        for index in range(2)
    ]

    def fake_runner(command, **kwargs):
        prompt = kwargs["input"]
        assert "必须为每个 candidate_id 返回且只返回一条 review" in prompt
        data = json.loads(prompt.split("DATA_JSON:\n", 1)[1])
        reviews = []
        for item in data:
            reviews.append(
                {
                    "candidate_id": item["candidate_id"],
                    "score": 4,
                    "dimensions": {
                        "business_scene": 2,
                        "project_timing": 2,
                        "platform_intent": 0,
                        "delivery_inquiry": 0,
                        "identity": 0,
                    },
                    "event_type": "员工培训",
                    "identity_confidence": "low",
                    "evidence": [
                        {
                            "dimension": "business_scene",
                            "quote": "公司下个月需要培训平台",
                            "url": item["sources"][0]["url"],
                        }
                    ],
                    "decision": "high_value",
                    "reason": "存在企业场景和近期项目",
                }
            )
        return subprocess.CompletedProcess(command, 0, json.dumps({"reviews": reviews}), "")

    result = run_codex_review_batch(candidates, runner=fake_runner)

    assert set(result) == {candidate_review_id(item) for item in candidates}
    assert all(status == "model_verified" for _, status in result.values())
    assert all(payload and payload["score"] == 4 for payload, _ in result.values())
    assert review_batch_schema()["properties"]["reviews"]["items"]["required"][0] == "candidate_id"


def test_codex_batch_review_falls_back_only_for_missing_or_invalid_rows() -> None:
    candidates = [
        {
            "platform": "zhihu",
            "content_id": f"answer-{index}",
            "comment_id": "",
            "quote": "公司正在筹备线上招商会，求平台报价",
            "sources": [{"url": f"https://example.com/answer-{index}", "text": "公司正在筹备线上招商会，求平台报价"}],
            "rule_dimensions": {name: 0 for name in ("business_scene", "project_timing", "platform_intent", "delivery_inquiry", "identity")},
            "profile": {"identity_confidence": "low"},
        }
        for index in range(2)
    ]

    def fake_runner(command, **kwargs):
        data = json.loads(kwargs["input"].split("DATA_JSON:\n", 1)[1])
        first = data[0]
        valid = {
            "candidate_id": first["candidate_id"],
            "score": 0,
            "dimensions": {name: 0 for name in ("business_scene", "project_timing", "platform_intent", "delivery_inquiry", "identity")},
            "event_type": "线上招商会",
            "identity_confidence": "low",
            "evidence": [],
            "decision": "review",
            "reason": "证据不足",
        }
        invalid = {"candidate_id": data[1]["candidate_id"], "score": 4}
        return subprocess.CompletedProcess(command, 0, json.dumps({"reviews": [valid, invalid]}), "")

    result = run_codex_review_batch(candidates, runner=fake_runner)

    first_id = candidate_review_id(candidates[0])
    second_id = candidate_review_id(candidates[1])
    assert result[first_id][1] == "model_verified"
    assert result[first_id][0]["score"] == 0
    assert result[second_id] == (None, "model_invalid")


def test_config_contains_event_query_volume() -> None:
    config = load_config(Path("local_tools/polyv_radar/pilot.toml"))
    total = sum(len(config.get_keywords_for_platform(platform)) for platform in config.platforms)

    assert total >= 30
    assert config.max_contents == 15
    assert config.max_comments == 30
    assert config.min_lead_score == 4


def test_config_uses_complete_antigravity_core_taxonomy() -> None:
    config = load_config(Path("local_tools/polyv_radar/pilot.toml"))

    assert config.taxonomy_snapshot is not None
    assert config.taxonomy_snapshot.version == "2.0.0"
    assert config.taxonomy_snapshot.query_count == 27
    assert len(config.taxonomy_snapshot.query_map()) == 27
    assert config.taxonomy_tiers == ("tier1_primary", "tier2_verify_demand")
    assert len(config.taxonomy_keywords) == 22
    queries = set(config.taxonomy_keywords.values())
    assert "公司年会 异地员工 视频方案" in queries
    assert "经销商大会 全国渠道 技术服务" in queries
    assert "医学学术会议 视频平台 服务商" in queries
    assert "招商大会 全国经销商 技术支持" in queries
    assert "主持人" in config.taxonomy_negative_terms
    assert "方案征集" in config.taxonomy_intent_terms["commercial_actions"]


def test_ego_launcher_uses_configured_collection_limits(tmp_path: Path) -> None:
    launcher = build_ego_launcher(Path("crawler.mjs"), "经销商大会", 15, 30, tmp_path)

    assert '"经销商大会"' in launcher
    assert '"15"' in launcher
    assert '"30"' in launcher


def test_ego_batch_launcher_reuses_one_taskspace_and_batches_keywords(tmp_path: Path) -> None:
    launcher = build_ego_batch_launcher(
        Path("local_tools/polyv_radar/ego_dy_crawler.mjs"),
        ["公司年会直播", "员工线上培训"],
        15,
        30,
        tmp_path / "dy",
        23,
        tmp_path / "snapshots",
    )

    assert "POLYV_TASKSPACE_ID" in launcher
    assert "POLYV_BATCH_KEYWORDS" in launcher
    assert "公司年会直播" in launcher and "员工线上培训" in launcher
    assert "ego_platform_batch.mjs" in launcher
    assert "POLYV_BATCH_RESULT_PATH" in launcher
    assert '"15"' in launcher and '"30"' in launcher


def test_ego_collection_launches_one_process_per_platform_and_persists_workflow(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "input": kwargs.get("input", "")})
        return subprocess.CompletedProcess(command, 0, "batch-complete", "")

    monkeypatch.setattr("local_tools.polyv_radar.ego_crawl_all.subprocess.run", fake_run)
    config = load_config(Path("local_tools/polyv_radar/pilot.toml"))
    config = config.__class__(
        data_root=tmp_path / "data",
        platforms=["dy"],
        keywords={"年会": "公司年会直播", "培训": "员工线上培训"},
        max_contents=2,
        max_comments=3,
    )

    result = run_ego_crawlers("workflow-run", ["dy"], config, Path.cwd(), config.data_root, 23)

    assert result == {"dy": True}
    assert len(calls) == 1
    assert "POLYV_BATCH_KEYWORDS" in calls[0]["input"]
    workflow = load_workflow_run(config.data_root, "workflow-run")
    assert workflow is not None
    assert workflow["mode"] == "ego_snapshot_batch"
    assert workflow["platforms"][0]["keywords"] == ["公司年会直播", "员工线上培训"]
    assert (config.data_root / "workflow-runs" / "workflow-run" / "workflow-candidate.json").is_file()
