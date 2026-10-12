import sqlite3
from pathlib import Path

from local_tools.polyv_radar.models import ProfileSnapshot
from local_tools.polyv_radar.profile_analysis import analyze_profile
from local_tools.polyv_radar.storage import RadarStore


def test_profile_analysis_detects_industry_and_company_exposure() -> None:
    result = analyze_profile(
        display_name="某教育科技",
        bio="教育行业 讲师 招生",
        posts=[{"title": "企业培训课程", "text": "AI 短视频招生"}],
        company="某教育科技有限公司",
        role="讲师",
    )
    assert result["industry"] == "教育培训"
    assert result["company_exposed"] is True
    assert result["company_name"] == "某教育科技有限公司"
    assert result["analysis_notes"].startswith("内部画像推测")


def test_profile_analysis_keeps_unknown_gender_and_age() -> None:
    result = analyze_profile(display_name="普通用户", bio="做销售", posts=[])
    assert result["gender_guess"] == "unknown"
    assert result["age_band_guess"] == "unknown"
    assert result["trend_alignment"] == "unknown"
    assert result["company_exposed"] is False


def test_explicit_peer_terms_can_produce_low_confidence_guesses() -> None:
    result = analyze_profile(
        display_name="宝妈做外贸",
        bio="出海 询盘 WhatsApp",
        posts=[{"title": "AI 短视频拓客", "text": "副业"}],
    )
    assert result["industry"] == "外贸跨境"
    assert result["gender_guess"] == "female"
    assert result["gender_confidence"] == "low"
    assert result["trend_alignment"] == "modern"


def test_profile_analysis_fields_round_trip_and_migrate(tmp_path: Path) -> None:
    store = RadarStore(tmp_path / "radar.sqlite3")
    store.initialize()
    store.upsert_profile(
        ProfileSnapshot(
            run_id="run-a",
            platform="dy",
            author_id="user-1",
            author_url="https://www.douyin.com/user/user-1",
            display_name="某教育科技",
            bio="教育行业",
            industry="教育培训",
            gender_guess="female",
            company_exposed=True,
            company_name="某教育科技有限公司",
            age_band_guess="young",
            trend_alignment="modern",
            analysis_evidence=["行业线索: 教育"],
            analysis_notes="内部画像推测",
        )
    )
    row = store.load_profiles("run-a")[0]
    assert row["industry"] == "教育培训"
    assert row["company_exposed"] == 1
    assert row["analysis_evidence"] == ["行业线索: 教育"]
    store.close()

    legacy = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.execute(
        """CREATE TABLE profiles (
           run_id TEXT NOT NULL, platform TEXT NOT NULL, author_id TEXT NOT NULL,
           author_url TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
           bio TEXT NOT NULL DEFAULT '', verified INTEGER NOT NULL DEFAULT 0,
           company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
           identity_confidence TEXT NOT NULL DEFAULT 'low',
           source_urls TEXT NOT NULL DEFAULT '[]', captured_at TEXT NOT NULL DEFAULT '',
           PRIMARY KEY (run_id, platform, author_id))"""
    )
    connection.commit()
    connection.close()
    migrated = RadarStore(legacy)
    migrated.initialize()
    columns = {row[1] for row in migrated.connection.execute("PRAGMA table_info(profiles)")}
    assert {"industry", "gender_guess", "company_exposed", "age_band_guess", "trend_alignment"} <= columns
    migrated.close()
