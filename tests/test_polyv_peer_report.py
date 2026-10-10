from __future__ import annotations

import json
from pathlib import Path

from local_tools.polyv_radar.peer_report import (
    build_peer_reports,
    build_promo_rows,
    extract_price_signals,
    load_peer_records,
    mask_contacts,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_peer_root(tmp_path: Path) -> Path:
    peer_root = tmp_path / "peer-research"
    query_dir = peer_root / "raw" / "peer-test-0001" / "zhihu" / "01-微吼 价格"
    write_jsonl(
        query_dir / "zhihu_contents.jsonl",
        [
            {
                "platform": "zhihu",
                "content_id": "c1",
                "title": "企业直播平台价格对比",
                "text": "微吼年费 3.5万元，小鹅通基础版 12800 元一年。公司有 7万 职工不适合；抽成 10% 的平台也要注意。",
                "url": "https://example.com/c1",
                "author": "行业观察",
                "published_at_raw": "2026-09-01",
            },
            {
                "platform": "zhihu",
                "content_id": "c2",
                "title": "求推荐企业直播平台",
                "text": "有人用过微吼吗？",
                "url": "https://example.com/c2",
                "author": "普通用户",
                "published_at_raw": "2026-08-01",
            },
            {
                "platform": "zhihu",
                "content_id": "c3",
                "title": "企业直播选微吼",
                "text": "我们提供企业直播服务。",
                "url": "https://example.com/c3",
                "author": "微吼官方",
                "published_at_raw": "2026-07-01",
            },
        ],
    )
    write_jsonl(
        query_dir / "zhihu_comments.jsonl",
        [
            {
                "platform": "zhihu",
                "comment_id": "m1",
                "content_id": "c1",
                "text": "想了解详情可以私信我，微信 abc_123，电话 13800000000",
                "author": "销售A",
                "published_at_raw": "2026-09-02",
            }
        ],
    )
    plan_dir = peer_root / "runs" / "peer-test-0001"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.json").write_text(
        json.dumps(
            {"queries": [{"platform": "zhihu", "query": "微吼 价格", "brand": "微吼"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return peer_root


def test_load_records_attaches_brand_and_parent_url(tmp_path):
    records = load_peer_records(make_peer_root(tmp_path))
    assert len(records) == 4
    assert {record["record_type"] for record in records} == {"content", "comment"}
    assert all(record["brand"] == "微吼" for record in records)
    comment = next(record for record in records if record["record_type"] == "comment")
    assert comment["url"] == "https://example.com/c1"
    assert comment["title"] == "企业直播平台价格对比"


def test_price_signals_include_currency_and_skip_non_price_numbers(tmp_path):
    records = load_peer_records(make_peer_root(tmp_path))
    signals = extract_price_signals(records)
    texts = {signal["price_text"] for signal in signals}
    assert "3.5万元" in texts
    assert "12800 元" in texts
    assert "抽成 10%" in texts
    assert "7万" not in texts
    sample = next(signal for signal in signals if signal["price_text"] == "3.5万元")
    assert sample["url"] == "https://example.com/c1"
    assert sample["author"] == "行业观察"
    assert sample["published"] == "2026-09-01"
    assert sample["signal_type"] == "报价金额"


def test_promo_rows_classify_vendor_roundup_and_user_discussion(tmp_path):
    records = load_peer_records(make_peer_root(tmp_path))
    brand_names = {"微吼", "小鹅通"}
    rows = build_promo_rows(records, brand_names)
    by_title = {row["title"]: row for row in rows if row["title"] and row["row_type"] != "评论区触达话术"}
    assert by_title["企业直播选微吼"]["row_type"] == "同行自家账号"
    assert by_title["企业直播平台价格对比"]["row_type"] == "测评或排行内容"
    assert by_title["求推荐企业直播平台"]["row_type"] == "用户讨论"
    outreach = [row for row in rows if row["row_type"] == "评论区触达话术"]
    assert len(outreach) == 1
    assert "私信" in outreach[0]["excerpt"]


def test_mask_contacts_hides_phone_wechat_and_email():
    masked = mask_contacts("微信 abc_123，电话 13800000000，邮箱 user@example.com")
    assert "13800000000" not in masked
    assert "abc_123" not in masked
    assert "user@example.com" not in masked
    assert "[手机号已遮蔽]" in masked


def test_mask_contacts_keeps_price_numbers():
    masked = mask_contacts("小鹅通基础版 6800 元/年，专业版 12800 元/年，旗舰版 25800 元/年")
    assert "6800" in masked
    assert "12800" in masked
    assert "25800" in masked


def test_build_reports_writes_csv_and_markdown(tmp_path):
    peer_root = make_peer_root(tmp_path)
    result = build_peer_reports(peer_root, output_dir=tmp_path / "reports")
    assert result["price_signals"] >= 3
    assert result["promo_rows"] >= 4
    price_csv = Path(result["price_csv"])
    promo_csv = Path(result["promo_csv"])
    assert price_csv.exists() and promo_csv.exists()
    assert "3.5万元" in price_csv.read_text(encoding="utf-8-sig")
    assert "评论区触达话术" in promo_csv.read_text(encoding="utf-8-sig")
    assert "同行价格情报表" in Path(result["price_markdown"]).read_text(encoding="utf-8")
    assert result["promo_counts"].get("评论区触达话术") == 1


def test_load_records_reads_douyin_videos_filename(tmp_path):
    peer_root = tmp_path / "peer-research"
    query_dir = peer_root / "raw" / "peer-test-0002" / "dy" / "01-微吼"
    write_jsonl(
        query_dir / "dy_videos.jsonl",
        [
            {
                "platform": "dy",
                "content_id": "v1",
                "title": "微吼直播企业直播宣传片",
                "text": "企业直播服务 2万元每场起",
                "url": "https://www.douyin.com/video/v1",
                "author": "微吼直播认证徽章北京微吼时代科技有限公司",
                "create_time": "2026-09-20T00:00:00.000Z",
            }
        ],
    )
    write_jsonl(
        query_dir / "dy_comments.jsonl",
        [
            {
                "platform": "dy",
                "comment_id": "v1_cm_1",
                "content_id": "v1",
                "text": "怎么联系你们",
                "author": "某用户",
                "published_at_raw": "2026-09-21",
            }
        ],
    )
    records = load_peer_records(peer_root)
    assert len(records) == 2
    content = next(record for record in records if record["record_type"] == "content")
    assert content["title"] == "微吼直播企业直播宣传片"
    assert content["url"] == "https://www.douyin.com/video/v1"
    comment = next(record for record in records if record["record_type"] == "comment")
    assert comment["url"] == "https://www.douyin.com/video/v1"


def test_promo_rows_dedupe_and_skip_own_accounts(tmp_path):
    records = [
        {
            "run_id": "r1", "platform": "zhihu", "query": "微吼", "record_type": "content",
            "record_id": "c1", "title": "企业直播平台对比", "text": "正文", "url": "https://example.com/c1",
            "author": "行业观察", "published": "2026-09-01", "brand": "微吼", "likes": 0,
        },
        {
            "run_id": "r2", "platform": "zhihu", "query": "企业直播平台 对比", "record_type": "content",
            "record_id": "c1", "title": "企业直播平台对比", "text": "正文", "url": "https://example.com/c1",
            "author": "行业观察", "published": "2026-09-01", "brand": "", "likes": 0,
        },
        {
            "run_id": "r1", "platform": "zhihu", "query": "微吼", "record_type": "comment",
            "record_id": "m1", "title": "企业直播平台对比", "text": "想了解可以私信我", "url": "https://example.com/c1",
            "author": "bugbg", "published": "2026-09-02", "brand": "微吼", "likes": 0,
        },
        {
            "run_id": "r1", "platform": "zhihu", "query": "微吼", "record_type": "comment",
            "record_id": "m2", "title": "企业直播平台对比", "text": "有需求私信我", "url": "https://example.com/c1",
            "author": "某销售", "published": "2026-09-02", "brand": "微吼", "likes": 0,
        },
    ]
    rows = build_promo_rows(records, {"微吼", "小鹅通"})
    assert len([row for row in rows if row["row_type"] == "测评或排行内容"]) == 1
    outreach = [row for row in rows if row["row_type"] == "评论区触达话术"]
    assert len(outreach) == 1
    assert outreach[0]["author"] == "某销售"
