from pathlib import Path

from local_tools.polyv_radar.cleaning import build_cleaning_rows
from local_tools.polyv_radar.config import RadarConfig
from local_tools.polyv_radar.models import LeadEvidence
from local_tools.polyv_radar.storage import RadarStore


def test_cleaning_marks_verified_history_and_keeps_target_not_found(tmp_path: Path) -> None:
    config = RadarConfig(data_root=tmp_path / "data", platforms=["dy"], keywords={"培训": "培训"})
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    store.save_leads(
        "run-1",
        [
            LeadEvidence(
                platform="dy", content_id="v-1", comment_id="c-1", url="https://example/v-1",
                user="甲", quote="公司正在找培训平台", category="企业培训", solution="企业培训方向", score=4,
                dimensions={"business_scene": 1, "project_timing": 1, "platform_intent": 1},
                stage="legacy_unverified", decision="legacy_unverified", locator_status="verified",
            ),
            LeadEvidence(
                platform="dy", content_id="v-2", comment_id="c-2", url="https://example/v-2",
                user="乙", quote="公司正在找培训平台", category="企业培训", solution="企业培训方向", score=4,
                stage="legacy_unverified", decision="legacy_unverified", locator_status="not_found",
            ),
        ],
    )
    store.close()
    evidence = tmp_path / "reply-evidence.json"
    evidence.write_text(
        '{"results":[{"run_id":"run-1","platform":"dy","content_id":"v-1",'
        '"comment_id":"c-1","reply_evidence_status":"text_not_found"}]}',
        encoding="utf-8",
    )
    rows = build_cleaning_rows(config, "run-1", evidence)
    by_id = {row["comment_id"]: row for row in rows}
    assert by_id["c-1"]["retry_status"] == "ready_for_skill_retry"
    assert by_id["c-2"]["retry_status"] == "not_sent_target_not_found"
