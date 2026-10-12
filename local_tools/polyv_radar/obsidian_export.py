"""Export the cumulative sent-leads board as an Obsidian Base + note set.

The HTML board (reports/all-sent-leads-dashboard.html) stays the source of
truth for counting: this exporter reuses load_combined_history() and
build_view() from cumulative_dashboard, so the vault and the board cannot
disagree about how many targets exist. It writes:

* one Markdown note per de-duplicated send target under <folder>/线索/;
* a Bases layout <folder>/雷达总览.base (created once; regenerate with
  --force-layout so hand-tuned views survive a re-export);
* an index note <folder>/雷达索引.md (same create-once rule);
* a regenerated <folder>/导出记录.md receipt with the current counts.

Only files carrying the generated_by marker are replaced or deleted, so
hand-written notes inside the same folder are never touched.

The vault keeps links and evidence paths only; screenshots, databases, cookies
and raw send logs stay outside the vault and outside git.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .cumulative_dashboard import (
    BRAND_LABELS,
    PLATFORM_LABELS,
    build_view,
    load_combined_history,
    target_key,
)

GENERATED_BY = "polyv-radar-obsidian-export"
DEFAULT_VAULT = Path("/Users/sexpistole111/Documents/claude學習/bugbg")
DEFAULT_FOLDER = "Poly/雷达"

SOURCE_TYPE_LABELS = {
    "comment": "评论",
    "reply": "子评论",
    "comment_reply": "子评论",
    "answer": "回答",
    "post": "帖子",
    "content": "内容",
}

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t#\^\[\]]')


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _yaml_str(value: object) -> str:
    """JSON-style quoting is valid YAML and keeps Chinese text readable."""
    return json.dumps(str(value or ""), ensure_ascii=False)


def _lead_id(key: tuple[str, str, str, str, str]) -> str:
    brand, platform, _author, _url, _quote = key
    digest = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:10]
    return f"{brand or 'polyv'}-{platform or 'unknown'}-{digest}"


def _safe_name(text: object, limit: int = 24) -> str:
    cleaned = _UNSAFE.sub("_", str(text or "").strip()) or "未知用户"
    return cleaned[:limit]


def _note_filename(row: dict, lead_id: str) -> str:
    brand = BRAND_LABELS.get(str(row.get("brand") or "polyv"), str(row.get("brand") or "polyv"))
    platform = PLATFORM_LABELS.get(str(row.get("platform") or ""), str(row.get("platform") or "未知"))
    return f"{brand}-{platform}-{_safe_name(row.get('target_author'))}-{lead_id.rsplit('-', 1)[-1]}.md"


def _status(row: dict) -> tuple[str, str]:
    verified = row.get("verified")
    clicked = row.get("clicked")
    if verified is True or (clicked is None and row.get("submitted") is True):
        return "sent_verified", "已发送并回查"
    if clicked is True:
        return "sent_unverified", "已发送待回查"
    return "not_sent", "未发送"


def _as_number(value: object) -> float | int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _file_uri(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return Path(text).expanduser().resolve().as_uri()
    except (OSError, ValueError):
        return ""


def _locator(row: dict) -> tuple[str, str]:
    direct = str(row.get("comment_url") or row.get("reply_url") or "").strip()
    if direct:
        return direct, "打开评论定位"
    content = str(row.get("target_url") or row.get("content_url") or row.get("url") or "").strip()
    source_label = SOURCE_TYPE_LABELS.get(str(row.get("source_type") or "").casefold(), "")
    if content and source_label in {"评论", "子评论"}:
        return content, "打开评论页（无独立锚点）"
    if content:
        return content, "打开目标页"
    return "", "未记录"


# --------------------------------------------------------------------------
# Score / profile enrichment from campaign lead files
# --------------------------------------------------------------------------


def _score_key(platform: object, author: object, quote: object) -> tuple[str, str, str] | None:
    platform_norm = _norm(platform)
    quote_norm = _norm(quote)
    if not (platform_norm and quote_norm):
        return None
    return (platform_norm, _norm(author), quote_norm[:40])


def load_lead_index(data_root: Path | str) -> dict[tuple[str, str, str], dict]:
    """Collect rule scores / profile hints from campaign JSON kept on disk.

    The send ledgers do not carry a score, so the board's 评分 column stays
    honest by only filling values that a lead file actually recorded. Two
    shapes are recognized: the new-leads export (records: [...]) and
    per-comment ZigoAI workflow snapshots.
    """
    root = Path(data_root)
    index: dict[tuple[str, str, str], dict] = {}
    candidates: list[dict] = []

    new_leads = root / "reports" / "20261012-new10-dy-sales-leads.json"
    if new_leads.is_file():
        try:
            payload = json.loads(new_leads.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            candidates.extend(item for item in payload.get("records") or [] if isinstance(item, dict))

    workflow_root = root / "zigoai" / "workflow-runs"
    if workflow_root.is_dir():
        for path in sorted(workflow_root.glob("**/*sales-comment*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "rule_score" in payload:
                candidates.append(payload)

    for record in candidates:
        key = _score_key(
            record.get("platform"),
            record.get("author") or record.get("target_author"),
            record.get("quote") or record.get("target_quote") or record.get("text"),
        )
        if key is None:
            continue
        entry = index.setdefault(key, {})
        for field in (
            "rule_score",
            "score",
            "need_type",
            "identity_confidence",
            "author_url",
            "author_id",
            "source_run",
            "campaign_id",
            "source_title",
        ):
            if entry.get(field) in (None, "") and record.get(field) not in (None, ""):
                entry[field] = record.get(field)
    return index


# --------------------------------------------------------------------------
# Note construction
# --------------------------------------------------------------------------


def _quote_block(text: str) -> str:
    lines = [line if line.strip() else " " for line in str(text or "未记录").splitlines()]
    return "\n".join("> " + line for line in lines)


def build_notes(view, data_root: Path | str) -> list[dict]:
    """Turn the keyed dashboard view into one note payload per target."""
    index = load_lead_index(data_root)
    notes: list[dict] = []
    for row in view.targets:
        key = target_key(row)
        lead_id = _lead_id(key)
        enriched = index.get(
            _score_key(row.get("platform"), row.get("target_author"), row.get("target_quote")) or ("", "", ""),
            {},
        )
        status, status_label = _status(row)
        sent_at = str(row.get("timestamp") or "")
        sent_date_match = _DATE.match(sent_at)
        sent_date = sent_date_match.group(1) if sent_date_match else ""
        verified_at = str(row.get("verified_at") or row.get("recheck_at") or "")
        brand = str(row.get("brand") or "polyv")
        brand_label = BRAND_LABELS.get(brand, brand)
        platform = str(row.get("platform") or "")
        platform_label = PLATFORM_LABELS.get(platform, platform or "未知")
        source_type = str(row.get("source_type") or "")
        source_label = SOURCE_TYPE_LABELS.get(source_type.casefold(), source_type or "未标注")
        locator_url, locator_label = _locator(row)
        score = _as_number(row.get("score")) or _as_number(enriched.get("rule_score"))
        score_source = ""
        if score is not None:
            score_source = "线索文件" if enriched.get("rule_score") not in (None, "") else "发送账本"
        reply_wave = int(row.get("reply_wave") or 1)
        batch = str(
            row.get("campaign_id") or row.get("run_id") or row.get("source_run") or enriched.get("source_run")
            or (sent_date[:7] if sent_date else "未标注")
        )
        screenshot = str(row.get("screenshot") or row.get("evidence_path") or "")
        screenshot_uri = _file_uri(screenshot)
        profile_url = str(row.get("author_url") or row.get("profile_url") or enriched.get("author_url") or "")
        author_id = str(row.get("author_id") or enriched.get("author_id") or "")
        content_url = str(row.get("target_url") or row.get("content_url") or row.get("url") or "")
        comment_url = str(row.get("comment_url") or "")
        failure_code = str(row.get("failure_code") or "")
        raw_notes = row.get("notes") or row.get("failure_reason") or row.get("verification") or ""
        if isinstance(raw_notes, (dict, list)):
            notes_text = json.dumps(raw_notes, ensure_ascii=False)
        else:
            notes_text = str(raw_notes)
        duplicate_of = row.get("_duplicate_of") or []
        quote = str(row.get("target_quote") or "")
        reply_text = str(row.get("reply_text") or "")
        received_reply = str(row.get("received_reply") or "")
        second_wave = bool(row.get("second_wave_reply"))

        tags = [
            "Poly/雷达",
            "Poly/雷达/线索",
            f"Poly/雷达/{platform_label}",
            f"Poly/雷达/{brand_label}",
        ]
        note = {
            "lead_id": lead_id,
            "path": _note_filename(row, lead_id),
            "row": row,
            "frontmatter": {
                "type": "radar-lead",
                "lead_id": lead_id,
                "brand": brand,
                "brand_label": brand_label,
                "product_domain": str(row.get("product_domain") or ""),
                "platform": platform,
                "platform_label": platform_label,
                "author": str(row.get("target_author") or ""),
                "author_id": author_id,
                "profile_url": profile_url,
                "source_type": source_type,
                "source_type_label": source_label,
                "content_url": content_url,
                "comment_url": comment_url,
                "locator_url": locator_url,
                "locator_label": locator_label,
                "quote": quote,
                "reply_text": reply_text,
                "status": status,
                "status_label": status_label,
                "sent_at": sent_at,
                "sent_date": sent_date,
                "verified_at": verified_at,
                "reply_wave": reply_wave,
                "reply_signal": str(row.get("reply_signal") or ""),
                "received_reply": received_reply,
                "reply_author": str(row.get("reply_author") or ""),
                "second_wave_reply": second_wave,
                "score": score,
                "score_source": score_source,
                "batch": batch,
                "candidate_id": str(row.get("candidate_id") or ""),
                "native_comment_id": str(row.get("native_comment_id") or ""),
                "own_account": str(row.get("own_account") or ""),
                "failure_code": failure_code,
                "notes": notes_text,
                "screenshot": screenshot,
                "duplicate_events": len(duplicate_of),
                "generated_by": GENERATED_BY,
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "tags": tags,
        }
        if note["frontmatter"].get("score") is None:
            # An empty string would poison numeric Base filters like
            # 'score >= 4'; an absent property is simply not matched.
            note["frontmatter"].pop("score", None)
            note["frontmatter"].pop("score_source", None)
        notes.append(note)
    return notes


def render_note(note: dict) -> str:
    fm = note["frontmatter"]
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        elif isinstance(value, list):
            if value:
                lines.append(f"{key}:")
                lines.extend(f"  - {_yaml_str(item)}" for item in value)
            else:
                lines.append(f"{key}: []")
        elif value in (None, ""):
            lines.append(f'{key}: ""')
        else:
            lines.append(f"{key}: {_yaml_str(value)}")
    lines.append("tags:")
    lines.extend(f"  - {_yaml_str(tag)}" for tag in note["tags"])
    lines.append("---")
    lines.append("")

    author = fm["author"] or "未知用户"
    lines.append(f"# {author}｜{fm['platform_label']}·{fm['brand_label']}")
    lines.append("")
    lines.append("> [!quote] 目标原话")
    lines.append(_quote_block(fm["quote"]))
    lines.append("")
    lines.append("## 我方回复")
    lines.append("")
    lines.append(fm["reply_text"] or "未记录")
    lines.append("")
    lines.append("## 发送与回查")
    lines.append("")
    lines.append(f"- 状态：{fm['status_label']}")
    lines.append(f"- 发送时间：{fm['sent_at'] or '未记录'}")
    lines.append(f"- 回查时间：{fm['verified_at'] or '未记录'}")
    lines.append(f"- 回复波次：{fm['reply_wave']}")
    if fm["received_reply"]:
        who = f"{fm['reply_author']}：" if fm.get("reply_author") else ""
        lines.append(f"- 对方回复：{who}{json.dumps(fm['received_reply'], ensure_ascii=False)}")
    if fm.get("score") is not None:
        lines.append(f"- 评分：{fm['score']}（{fm.get('score_source') or '未标注来源'}）")
    lines.append(f"- 批次：{fm['batch']}")
    if fm["duplicate_events"]:
        lines.append(f"- 重复触达：{fm['duplicate_events']} 次（同一目标再次发送）")
    lines.append("")
    lines.append("## 证据")
    lines.append("")
    if fm["content_url"]:
        lines.append(f"- 来源（{fm['source_type_label']}）：[打开来源]({fm['content_url']})")
    else:
        lines.append("- 来源：未记录")
    if fm["locator_url"]:
        lines.append(f"- 评论定位：[{fm['locator_label']}]({fm['locator_url']})")
    if fm["profile_url"]:
        lines.append(f"- 用户主页：[打开主页]({fm['profile_url']})")
    if fm["screenshot"]:
        uri = _file_uri(fm["screenshot"])
        lines.append(f"- 发送证据：[查看截图]({uri})" if uri else f"- 发送证据：{fm['screenshot']}")
    if fm["native_comment_id"]:
        lines.append(f"- 原生评论 ID：{fm['native_comment_id']}")
    if fm["candidate_id"]:
        lines.append(f"- 候选 ID：{fm['candidate_id']}")
    if fm["failure_code"] or fm["notes"]:
        lines.append("")
        lines.append("## 备注")
        lines.append("")
        if fm["failure_code"]:
            lines.append(f"- 失败/状态码：{fm['failure_code']}")
        if fm["notes"]:
            lines.append(f"- {fm['notes']}")
    lines.append("")
    lines.append("<!-- polyv-radar-obsidian-export -->")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Bases layout
# --------------------------------------------------------------------------


def render_base() -> str:
    return """filters:
  and:
    - 'file.hasTag("Poly/雷达/线索")'

formulas:
  status_icon: 'if(status == "sent_verified", "✅", if(status == "sent_unverified", "⏳", "•"))'
  wave_label: 'if(reply_wave && reply_wave >= 2, "二次回复待设计", "")'
  days_since_sent: 'if(sent_date, (today() - date(sent_date)).days, "")'
  needs_action: 'if(status == "sent_unverified" || (reply_wave && reply_wave >= 2), "待处理", "")'

properties:
  author:
    displayName: 用户
  brand_label:
    displayName: 品牌
  platform_label:
    displayName: 平台
  quote:
    displayName: 原话
  status_label:
    displayName: 状态
  formula.status_icon:
    displayName: ""
  sent_at:
    displayName: 发送时间
  sent_date:
    displayName: 发送日期
  score:
    displayName: 评分
  batch:
    displayName: 批次
  reply_wave:
    displayName: 波次
  formula.wave_label:
    displayName: 二级信号
  received_reply:
    displayName: 对方回复
  reply_text:
    displayName: 我方回复
  locator_url:
    displayName: 评论定位
  content_url:
    displayName: 来源
  screenshot:
    displayName: 截图
  failure_code:
    displayName: 失败码
  notes:
    displayName: 备注
  formula.days_since_sent:
    displayName: 距发送天数
  formula.needs_action:
    displayName: 待办

views:
  - type: table
    name: 全部线索
    order:
      - author
      - formula.status_icon
      - status_label
      - brand_label
      - platform_label
      - quote
      - score
      - sent_at
      - formula.days_since_sent
      - batch
      - reply_text
      - locator_url
      - content_url
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 待回查
    filters:
      and:
        - 'status == "sent_unverified"'
    order:
      - author
      - brand_label
      - platform_label
      - quote
      - sent_at
      - formula.days_since_sent
      - failure_code
      - locator_url
      - screenshot
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 已回查
    filters:
      and:
        - 'status == "sent_verified"'
    order:
      - author
      - brand_label
      - platform_label
      - quote
      - sent_at
      - verified_at
      - reply_wave
      - locator_url
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 二次回复待设计
    filters:
      and:
        - 'reply_wave >= 2'
    order:
      - author
      - platform_label
      - quote
      - received_reply
      - sent_at
      - locator_url
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 4分以上线索
    filters:
      and:
        - 'score >= 4'
    order:
      - author
      - brand_label
      - platform_label
      - quote
      - score
      - score_source
      - status_label
      - sent_at
      - locator_url
    sort:
      - property: score
        direction: DESC
  - type: table
    name: POLYV
    filters:
      and:
        - 'brand == "polyv"'
    order:
      - author
      - platform_label
      - quote
      - status_label
      - sent_at
      - batch
      - locator_url
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: ZigoAI
    filters:
      and:
        - 'brand == "zigo"'
    order:
      - author
      - platform_label
      - quote
      - status_label
      - sent_at
      - batch
      - locator_url
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 按平台
    groupBy:
      property: platform_label
      direction: ASC
    order:
      - author
      - brand_label
      - quote
      - status_label
      - sent_at
    sort:
      - property: sent_at
        direction: DESC
  - type: table
    name: 按批次
    groupBy:
      property: batch
      direction: DESC
    order:
      - author
      - brand_label
      - platform_label
      - quote
      - status_label
      - sent_at
    sort:
      - property: sent_at
        direction: DESC
"""


def render_index(stats: dict) -> str:
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return f"""---
type: index
updated_at: {today}
tags:
  - Poly
  - Poly/雷达
---

# 雷达 · 发送线索大板（Obsidian Base）

> [!info] 口径
> - 与 HTML 大板同源：reply_history.jsonl + zigoai/**/send-log.json + reply_signals.jsonl
> - 去重键：品牌 + 平台 + 作者 + 来源链接 + 目标原话（不含回复文案）
> - “已发送并回查”只表示我方发送成功且页面回查通过；对方是否回复单独看“对方回复”
> - 线索/ 内笔记由导出器生成，手工内容请另建笔记；视图定义在 [[雷达总览.base]]
> - 最近一次导出：[[导出记录]]（{stats.get('target_count', 0)} 条去重线索 / {stats.get('event_count', 0)} 条原始记录）

## 核心视图

![[雷达总览.base#待回查]]

![[雷达总览.base#二次回复待设计]]

![[雷达总览.base#4分以上线索]]

## 其他视图

- 全部线索、已回查、POLYV、ZigoAI、按平台、按批次：打开 [[雷达总览.base]]
- 数据源 HTML 大板：/Users/sexpistole111/Documents/workplace/polyv-radar-data/reports/all-sent-leads-dashboard.html
"""


def render_receipt(stats: dict) -> str:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "---",
        "type: radar-export-receipt",
        f"generated_at: {_yaml_str(generated_at)}",
        f"generated_by: {GENERATED_BY}",
        "tags:",
        '  - "Poly/雷达"',
        "---",
        "",
        "# 雷达导出记录",
        "",
        f"- 导出时间：{generated_at}",
        f"- 去重后发送线索：{stats.get('target_count', 0)}",
        f"- 原始已发送记录：{stats.get('event_count', 0)}",
        f"- 重复触达：{stats.get('duplicate_events', 0)}",
        f"- 已发送并回查：{stats.get('verified_count', 0)}",
        f"- 已发送待回查：{stats.get('unverified_count', 0)}",
        f"- 二次回复待设计：{stats.get('second_wave_count', 0)}",
        f"- 评分 ≥ 4：{stats.get('scored_count', 0)}",
        f"- 写入笔记：{stats.get('notes_written', 0)}",
        f"- 清理过期笔记：{stats.get('notes_removed', 0)}",
        "",
        "## 分布",
        "",
        "| 品牌 | 数量 |",
        "| --- | --- |",
    ]
    for brand, count in sorted(stats.get("brand_counts", {}).items()):
        lines.append(f"| {brand} | {count} |")
    lines.append("")
    lines.append("| 平台 | 数量 |")
    lines.append("| --- | --- |")
    for platform, count in sorted(stats.get("platform_counts", {}).items()):
        lines.append(f"| {platform} | {count} |")
    lines.append("")
    lines.append("<!-- polyv-radar-obsidian-export -->")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Export entry point
# --------------------------------------------------------------------------


def _write_if_missing(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def export_to_vault(
    ledger_path: Path | str,
    data_root: Path | str,
    vault_root: Path | str = DEFAULT_VAULT,
    folder: str = DEFAULT_FOLDER,
    *,
    force_layout: bool = False,
) -> dict:
    """Export the cumulative board into vault_root/folder and return stats."""
    ledger = Path(ledger_path)
    root = Path(data_root)
    target_dir = Path(vault_root).expanduser() / folder
    notes_dir = target_dir / "线索"

    rows = load_combined_history(ledger, root)
    view = build_view(rows)
    notes = build_notes(view, root)

    notes_dir.mkdir(parents=True, exist_ok=True)
    expected = {note["path"] for note in notes}
    written = 0
    for note in notes:
        (notes_dir / note["path"]).write_text(render_note(note), encoding="utf-8")
        written += 1

    removed = 0
    for stale in notes_dir.glob("*.md"):
        if stale.name in expected:
            continue
        head = stale.read_text(encoding="utf-8", errors="replace")
        if GENERATED_BY in head and "generated_by" in head:
            stale.unlink()
            removed += 1

    stats = {
        "event_count": view.event_count,
        "duplicate_events": view.duplicate_events,
        "target_count": view.target_count,
        "verified_count": sum(1 for row in view.targets if _status(row)[0] == "sent_verified"),
        "unverified_count": sum(1 for row in view.targets if _status(row)[0] == "sent_unverified"),
        "second_wave_count": sum(1 for row in view.targets if row.get("second_wave_reply")),
        "scored_count": sum(
            1
            for note in notes
            if isinstance(note["frontmatter"].get("score"), (int, float))
            and note["frontmatter"]["score"] >= 4
        ),
        "notes_written": written,
        "notes_removed": removed,
        "brand_counts": {},
        "platform_counts": {},
    }
    for note in notes:
        brand = note["frontmatter"]["brand_label"]
        platform = note["frontmatter"]["platform_label"]
        stats["brand_counts"][brand] = stats["brand_counts"].get(brand, 0) + 1
        stats["platform_counts"][platform] = stats["platform_counts"].get(platform, 0) + 1

    layout_written = {
        "base": _write_if_missing(target_dir / "雷达总览.base", render_base(), force_layout),
        "index": _write_if_missing(target_dir / "雷达索引.md", render_index(stats), force_layout),
    }
    (target_dir / "导出记录.md").write_text(render_receipt(stats), encoding="utf-8")

    stats["vault_dir"] = str(target_dir)
    stats["notes_dir"] = str(notes_dir)
    stats["layout_written"] = layout_written
    return stats
