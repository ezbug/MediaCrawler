from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


_CAMPAIGN_TOKEN = re.compile(r"\d+")
_QUALIFIED_STATES = {"qualified", "qualified_candidate", "human_confirmed_qualified"}
_RESOLVED_QUALITY_STATES = _QUALIFIED_STATES | {"not_established", "publisher_not_prospect", "rejected"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    # Drop transient access tokens while keeping stable paths and comment anchors.
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", "", parts.fragment))


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _hash_identity(parts: list[object]) -> str:
    payload = "\x1f".join(str(part or "").strip() for part in parts)
    return _sha256(payload.encode("utf-8"))


def _read_jsonl(path: Path) -> list[tuple[int, dict, str]]:
    rows: list[tuple[int, dict, str]] = []
    if not path.is_file():
        return rows
    for line_number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} 不是有效 JSONL") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
        rows.append((line_number, value, _sha256(raw)))
    return rows


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取交接源文件 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"交接源文件必须是 JSON 对象: {path}")
    return value


def _campaign_tag(campaign: str) -> str:
    match = _CAMPAIGN_TOKEN.search(campaign)
    if not match:
        raise ValueError("campaign 名称需要包含目标数量，例如 polyv-100")
    return f"leads{match.group(0)}"


def _resolve_sources(
    data_root: Path,
    campaign: str,
    queue_path: Path | None,
    results_path: Path | None,
) -> tuple[Path, Path | None, str]:
    tag = _campaign_tag(campaign)
    dispatch_dir = data_root / "dispatch"
    if queue_path is None:
        matches = sorted(dispatch_dir.glob(f"*-{tag}-strict.jsonl"))
        if len(matches) != 1:
            raise ValueError(
                f"campaign {campaign} 匹配到 {len(matches)} 个严格队列；"
                "请通过 --queue 明确指定唯一队列。"
            )
        queue_path = matches[0]
    queue_path = Path(queue_path).expanduser().resolve()
    if tag not in queue_path.name or "strict" not in queue_path.name:
        raise ValueError(f"队列路径与 campaign {campaign} 不匹配: {queue_path}")
    prefix = queue_path.stem.removesuffix("-strict")
    if results_path is None:
        expected = dispatch_dir / f"dispatch-{queue_path.stem}-live.jsonl"
        results_path = expected if expected.is_file() else None
    elif results_path is not None:
        results_path = Path(results_path).expanduser().resolve()
        if prefix not in results_path.name or "live" not in results_path.name:
            raise ValueError(f"发送结果路径与 campaign {campaign} 不匹配: {results_path}")
    if not queue_path.is_file():
        raise ValueError(f"发送队列不存在: {queue_path}")
    if results_path is not None and not results_path.is_file():
        raise ValueError(f"发送结果文件不存在: {results_path}")
    return queue_path, Path(results_path) if results_path else None, prefix


def _load_candidate_pool(data_root: Path, prefix: str) -> tuple[list[dict], list[Path]]:
    input_path = data_root / "locators" / f"{prefix}-input.json"
    output_path = data_root / "locators" / f"{prefix}-output.json"
    paths = [path for path in (input_path, output_path) if path.is_file()]
    inputs: dict[str, dict] = {}
    if input_path.is_file():
        for row in _read_json(input_path).get("candidates", []):
            if isinstance(row, dict):
                inputs[str(row.get("candidate_id", ""))] = row
    if output_path.is_file():
        outputs = _read_json(output_path).get("results", [])
        merged = []
        for output in outputs:
            if not isinstance(output, dict):
                continue
            candidate_id = str(output.get("candidate_id", ""))
            merged.append({**inputs.get(candidate_id, {}), **output})
        return merged, paths
    return list(inputs.values()), paths


def _record_identity(row: dict) -> tuple[str, str, str, str, str]:
    platform = str(row.get("platform", "")).strip()
    content_id = str(row.get("content_id", "")).strip()
    comment_id = str(row.get("native_comment_id") or row.get("comment_id") or "").strip()
    author_id = str(row.get("author_id", "")).strip()
    url = _canonical_url(row.get("url") or row.get("content_url") or row.get("locator_url"))
    author = str(row.get("author") or row.get("user") or "").strip()
    quote = _norm(row.get("quote") or row.get("text"))
    return platform, content_id, comment_id, author_id, _hash_identity([url, author_id or author, quote])


def _record_keys(row: dict) -> tuple[str, str]:
    platform, content_id, comment_id, author_id, fallback = _record_identity(row)
    record_key = _hash_identity([platform, content_id, comment_id, author_id, fallback])
    if author_id:
        dedupe_key = _hash_identity([platform, "author_id", author_id])
        dedupe_basis = "platform_author_id"
    else:
        # Do not merge accounts by display name; unknown identities remain record-scoped.
        dedupe_key = _hash_identity([platform, "record", record_key])
        dedupe_basis = "record_fallback_no_stable_author_id"
    return record_key, dedupe_key


def _match_candidate(action: dict, candidates: list[dict]) -> int | None:
    platform = str(action.get("platform", ""))
    author = _norm(action.get("author"))
    quote = _norm(action.get("quote"))
    content_id = str(action.get("content_id", "")).strip()
    comment_id = str(action.get("comment_id", "")).strip()
    action_url = _canonical_url(action.get("content_url") or action.get("url"))
    matches: list[int] = []
    for index, candidate in enumerate(candidates):
        if candidate.get("platform") != platform:
            continue
        candidate_author = _norm(candidate.get("user") or candidate.get("author"))
        candidate_quote = _norm(candidate.get("quote"))
        candidate_content = str(candidate.get("content_id", "")).strip()
        candidate_comment = str(candidate.get("native_comment_id") or candidate.get("comment_id") or "").strip()
        candidate_url = _canonical_url(candidate.get("content_url") or candidate.get("url") or candidate.get("locator_url"))
        comment_overlap = bool(
            comment_id and candidate_comment and (
                comment_id == candidate_comment
                or comment_id.endswith("_" + candidate_comment)
                or candidate_comment.endswith("_" + comment_id)
            )
        )
        id_overlap = bool(
            comment_overlap
            or (content_id and candidate_content and content_id == candidate_content)
        )
        identifiers_conflict = bool(
            (content_id and candidate_content and content_id != candidate_content)
            or (comment_id and candidate_comment and not comment_overlap)
        )
        link_overlap = bool(action_url and candidate_url and action_url == candidate_url)
        if not identifiers_conflict and (id_overlap or link_overlap) and author == candidate_author and quote == candidate_quote:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def _match_history(action: dict, history_rows: list[tuple[int, dict, str]]) -> tuple[int, dict, str] | None:
    wanted = (
        str(action.get("platform", "")),
        _canonical_url(action.get("url")),
        _norm(action.get("author")),
        _norm(action.get("text")),
    )
    matches = []
    for row in history_rows:
        value = row[1]
        candidate = (
            str(value.get("platform", "")),
            _canonical_url(value.get("target_url")),
            _norm(value.get("target_author")),
            _norm(value.get("reply_text")),
        )
        if candidate == wanted and value.get("mode") != "dry_run":
            matches.append(row)
    return matches[-1] if matches else None


def _match_result(action: dict, result_rows: list[tuple[int, dict, str]]) -> tuple[int, dict, str] | None:
    wanted = (
        str(action.get("platform", "")),
        _canonical_url(action.get("url")),
        _norm(action.get("author")),
        _norm(action.get("quote")),
        _norm(action.get("text")),
    )
    matches = []
    for row in result_rows:
        value = row[1]
        candidate = (
            str(value.get("platform", "")),
            _canonical_url(value.get("url")),
            _norm(value.get("author")),
            _norm(value.get("quote")),
            _norm(value.get("text")),
        )
        if candidate == wanted:
            matches.append(row)
    return matches[-1] if matches else None


def _quality_for(row: dict, review_rows: list[dict]) -> dict:
    identifiers = {
        "platform": str(row.get("platform", "")),
        "candidate_id": str(row.get("candidate_id", "")),
        "content_id": str(row.get("content_id", "")),
        "comment_id": str(row.get("native_comment_id") or row.get("comment_id") or ""),
        "author": _norm(row.get("user") or row.get("author")),
        "quote": _norm(row.get("quote")),
    }
    matches = []
    for review in review_rows:
        if str(review.get("platform", "")) != identifiers["platform"]:
            continue
        if review.get("candidate_id") and review.get("candidate_id") == identifiers["candidate_id"]:
            matches.append(review)
            continue
        review_comment = str(review.get("comment_id", ""))
        id_match = bool(
            (identifiers["comment_id"] and review_comment and (
                review_comment == identifiers["comment_id"]
                or review_comment.endswith("_" + identifiers["comment_id"])
                or identifiers["comment_id"].endswith("_" + review_comment)
            ))
            or (identifiers["content_id"] and review.get("content_id") == identifiers["content_id"])
        )
        author_match = _norm(review.get("author") or review.get("user")) == identifiers["author"]
        quote_match = _norm(review.get("quote")) == identifiers["quote"]
        if id_match and author_match and quote_match:
            matches.append(review)
    if len(matches) == 1:
        return {
            "status": str(matches[0].get("quality_status", "needs_review")),
            "reason": str(matches[0].get("quality_reason", "")),
            "reviewed_by": str(matches[0].get("reviewed_by", "")),
            "review_evidence": matches[0].get("evidence", []),
        }
    if len(matches) > 1:
        return {"status": "ambiguous_review", "reason": "多个质量复核记录匹配，未自动选择。"}
    return {"status": "not_reviewed", "reason": "没有与本条记录唯一匹配的质量复核记录。"}


def _load_db_context(database_path: Path) -> tuple[dict, dict]:
    if not database_path.is_file():
        return {}, {}
    uri = database_path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        content_rows = {}
        comment_rows = {}
        if "contents" in tables:
            for row in connection.execute(
                "SELECT platform, content_id, title, url, author, author_id, author_url, published_at FROM contents"
            ):
                content_rows[(row["platform"], row["content_id"])] = dict(row)
        if "comments" in tables:
            for row in connection.execute(
                "SELECT platform, comment_id, content_id, text, author, author_id, author_url, "
                "parent_comment_id, native_comment_id, native_parent_id, published_at FROM comments"
            ):
                item = dict(row)
                keys = {(item["platform"], item["comment_id"])}
                if item["native_comment_id"]:
                    keys.add((item["platform"], item["native_comment_id"]))
                comment_rows.update({key: item for key in keys})
        return content_rows, comment_rows
    finally:
        connection.close()


def _comment_context(row: dict, comment_rows: dict) -> dict | None:
    platform = str(row.get("platform", ""))
    candidates = [str(row.get("native_comment_id") or row.get("comment_id") or "").strip()]
    if candidates[0] and "_" in candidates[0]:
        candidates.append(candidates[0].rsplit("_", 1)[-1])
    for candidate in candidates:
        if candidate and (platform, candidate) in comment_rows:
            return comment_rows[(platform, candidate)]
    content_id = _content_id(row)
    author = _norm(row.get("author") or row.get("user"))
    quote = _norm(row.get("quote"))
    if content_id and author and quote:
        unique = {
            (item["platform"], item["comment_id"]): item
            for item in comment_rows.values()
            if item.get("platform") == platform
            and item.get("content_id") == content_id
            and _norm(item.get("author")) == author
            and _norm(item.get("text")) == quote
        }
        if len(unique) == 1:
            return next(iter(unique.values()))
    return None


def _content_id(row: dict) -> str:
    content_id = str(row.get("content_id", "")).strip()
    if content_id:
        return content_id
    raw_url = str(row.get("content_url") or row.get("url") or row.get("locator_url") or "")
    parts = [part for part in urlsplit(raw_url).path.split("/") if part]
    platform = str(row.get("platform", ""))
    route = "explore" if platform == "xhs" else "answer" if platform == "zhihu" else "video"
    if route in parts and len(parts) > parts.index(route) + 1:
        return parts[parts.index(route) + 1]
    comment_id = str(row.get("native_comment_id") or row.get("comment_id") or "")
    if "_" in comment_id:
        return comment_id.split("_", 1)[0]
    return ""


def _enrich_from_db(row: dict, content_rows: dict, comment_rows: dict) -> dict:
    platform = str(row.get("platform", ""))
    content_id = _content_id(row)
    content = content_rows.get((platform, content_id), {})
    comment = _comment_context(row, comment_rows) if row.get("source_type") not in {"answer", "post"} else None
    candidate = dict(row)
    candidate["content_id"] = candidate.get("content_id") or content_id
    if comment:
        for key, source_key in (("author_id", "author_id"), ("author_url", "author_url"), ("published_at", "published_at"), ("parent_comment_id", "parent_comment_id")):
            candidate[key] = candidate.get(key) or comment.get(source_key, "")
        candidate["quote"] = candidate.get("quote") or comment.get("text", "")
    if content:
        candidate["content_title"] = content.get("title", "")
        candidate["content_author"] = content.get("author", "")
        candidate["content_author_id"] = content.get("author_id", "")
        candidate["content_published_at"] = content.get("published_at", "")
        candidate["content_url"] = candidate.get("content_url") or content.get("url", "")
        if candidate.get("source_type") in {"answer", "post"}:
            candidate["author_id"] = candidate.get("author_id") or content.get("author_id", "")
            candidate["author_url"] = candidate.get("author_url") or content.get("author_url", "")
            candidate["published_at"] = candidate.get("published_at") or content.get("published_at", "")
    return candidate


def _line_reference(path: Path, line: tuple[int, dict, str] | None) -> dict:
    if not line:
        return {}
    return {"path": str(path), "line": line[0], "row_sha256": line[2]}


def _source_list(
    data_root: Path,
    prefix: str,
    queue_path: Path,
    results_path: Path | None,
    history_path: Path,
    review_path: Path | None,
    candidate_paths: list[Path],
    screenshot_paths: list[Path],
) -> list[dict]:
    paths = {queue_path, history_path}
    if results_path:
        paths.add(results_path)
    database_path = data_root / "radar.sqlite3"
    if database_path.is_file():
        paths.add(database_path)
    paths.update(candidate_paths)
    if review_path and review_path.is_file():
        paths.add(review_path)
    for folder in ("dispatch", "review", "locators", "reports"):
        directory = data_root / folder
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_file() and (path.name.startswith(prefix) or f"{prefix}-" in path.name):
                    paths.add(path)
    paths.update(path for path in screenshot_paths if path.is_file())
    sources = []
    for path in sorted(paths, key=lambda item: str(item)):
        if path.is_file():
            sources.append({"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": _file_hash(path)})
    return sources


def _write_immutable(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return False
        raise FileExistsError(f"交接快照路径已存在且内容不同，拒绝覆盖: {path}")
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("xb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        temp_path.chmod(0o444)
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise FileExistsError(f"并发生成了不同内容的交接快照，拒绝覆盖: {path}")
            return False
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def _resolve_quality_review(data_root: Path, campaign: str, supplied: Path | None) -> Path | None:
    if supplied is not None:
        path = Path(supplied).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"质量复核文件不存在: {path}")
        return path
    default = data_root / "review" / f"{campaign}-quality-review.jsonl"
    return default if default.is_file() else None


def export_handoff(
    data_root: Path,
    campaign: str,
    repo_root: Path,
    revision: str | None = None,
    queue_path: Path | None = None,
    results_path: Path | None = None,
    quality_review_path: Path | None = None,
    reply_history_path: Path | None = None,
    write: bool = True,
) -> dict:
    data_root = Path(data_root).expanduser().resolve()
    repo_root = Path(repo_root).expanduser().resolve()
    queue_path, results_path, prefix = _resolve_sources(data_root, campaign, queue_path, results_path)
    history_path = Path(reply_history_path or data_root / "reply_history.jsonl").expanduser().resolve()
    review_path = _resolve_quality_review(data_root, campaign, quality_review_path)
    if not history_path.is_file():
        raise ValueError(f"发送历史账本不存在: {history_path}")

    if revision is None:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=False
        )
        if completed.returncode:
            raise ValueError(f"无法读取当前 Git revision: {completed.stderr.strip()}")
        revision = completed.stdout.strip()

    queue_rows = _read_jsonl(queue_path)
    result_rows = _read_jsonl(results_path) if results_path else []
    history_rows = _read_jsonl(history_path)
    review_rows = _read_jsonl(review_path) if review_path else []
    candidates, candidate_paths = _load_candidate_pool(data_root, prefix)
    database_path = data_root / "radar.sqlite3"
    content_rows, comment_rows = _load_db_context(database_path)
    candidates = [_enrich_from_db(row, content_rows, comment_rows) for row in candidates]

    record_rows: list[dict] = []
    for candidate in candidates:
        record_key, dedupe_key = _record_keys(candidate)
        record_rows.append({
            "record_key": record_key,
            "dedupe_key": dedupe_key,
            "dedupe_basis": "platform_author_id" if candidate.get("author_id") else "record_fallback_no_stable_author_id",
            "source_scope": "locator_candidate",
            "candidate_id": candidate.get("candidate_id", ""),
            "platform": candidate.get("platform", ""),
            "source_type": candidate.get("source_type", ""),
            "content_id": candidate.get("content_id", ""),
            "comment_id": candidate.get("native_comment_id") or candidate.get("comment_id", ""),
            "parent_comment_id": candidate.get("parent_comment_id", ""),
            "content_title": candidate.get("content_title", ""),
            "content_url": _canonical_url(candidate.get("content_url") or candidate.get("locator_url")),
            "comment_url": _canonical_url(candidate.get("comment_url") or candidate.get("locator_url")),
            "user": candidate.get("user") or candidate.get("author", ""),
            "author_id": candidate.get("author_id", ""),
            "author_url": _canonical_url(candidate.get("author_url")),
            "published_at": candidate.get("published_at", ""),
            "quote": candidate.get("quote", ""),
            "locator": {
                "status": candidate.get("status", "not_run"),
                "method": candidate.get("locator_method", ""),
                "reason": candidate.get("reason", ""),
                "verified_at": candidate.get("verified_at", ""),
                "final_url": _canonical_url(candidate.get("final_url")),
                "reply_evidence_status": candidate.get("reply_evidence_status", ""),
                "reply_evidence_reason": candidate.get("reply_evidence_reason", ""),
            },
            "quality": _quality_for(candidate, [row[1] for row in review_rows]),
            "dispatch": [],
        })

    screenshot_paths: list[Path] = []
    dispatch_verified = 0
    runtime_verified = 0
    action_status_counts: Counter[str] = Counter()
    for _, queue_row, queue_hash in queue_rows:
        action = _enrich_from_db(dict(queue_row), content_rows, comment_rows)
        result_match = _match_result(action, result_rows)
        history_match = _match_history(action, history_rows)
        result_value = result_match[1] if result_match else {}
        history_value = history_match[1] if history_match else {}
        is_dispatch_verified = (
            result_value.get("status") == "submitted_verified"
            and result_value.get("submitted") is True
            and result_value.get("verified") is True
        )
        is_history_verified = history_value.get("submitted") is True and history_value.get("verified") is True
        if is_dispatch_verified:
            dispatch_verified += 1
        if is_dispatch_verified and is_history_verified:
            status = "submitted_verified"
            runtime_verified += 1
        elif result_value.get("status") == "submitted_verified" and not is_history_verified:
            status = "reported_verified_history_missing"
        elif history_match and is_history_verified and not is_dispatch_verified:
            status = "history_verified_result_missing"
        else:
            status = str(result_value.get("status") or queue_row.get("status") or "queued_unresolved")
        action_status_counts[status] += 1
        screenshot_value = str(result_value.get("screenshot") or history_value.get("screenshot") or "")
        screenshot = Path(screenshot_value).expanduser() if screenshot_value and screenshot_value != "screenshot_skipped" else None
        screenshot_sha = ""
        visual_state = "not_available"
        if screenshot and screenshot.is_file():
            screenshot_paths.append(screenshot.resolve())
            screenshot_sha = _file_hash(screenshot)
            visual_state = "draft_preview_only" if screenshot.name.startswith("reply_preview_") else "artifact_not_semantically_reviewed"
        elif screenshot_value:
            visual_state = "referenced_file_missing"
        action_record = {
            "queue": {"path": str(queue_path), "row_sha256": queue_hash},
            "result": {
                **(_line_reference(results_path, result_match) if results_path else {}),
                "status": result_value.get("status", ""),
                "submitted": result_value.get("submitted", False),
                "verified": result_value.get("verified", False),
                "target_matched": result_value.get("target_matched", False),
            },
            "status": status,
            "reply_text": str(action.get("text", "")),
            "reply_history_match": bool(history_match),
            "reply_history": {
                **_line_reference(history_path, history_match),
                "submitted": history_value.get("submitted", False),
                "verified": history_value.get("verified", False),
                "timestamp": history_value.get("timestamp", ""),
                "mode": history_value.get("mode", ""),
            },
            "screenshot": {
                "path": screenshot_value,
                "sha256": screenshot_sha,
                "visual_evidence_state": visual_state,
                "post_send_screenshot": False if visual_state == "draft_preview_only" else None,
            },
            "evidence_limit": "截图为发送前预览；发送后的文本核验仅由匹配的结构化 reply_history 记录证明。",
        }
        match_index = _match_candidate(action, candidates)
        if match_index is None:
            record_key, dedupe_key = _record_keys(action)
            candidate_record = {
                "record_key": record_key,
                "dedupe_key": dedupe_key,
                "dedupe_basis": "platform_author_id" if action.get("author_id") else "record_fallback_no_stable_author_id",
                "source_scope": "dispatch_only",
                "candidate_id": action.get("candidate_id", ""),
                "platform": action.get("platform", ""),
                "source_type": action.get("source_type", ""),
                "content_id": action.get("content_id", ""),
                "comment_id": action.get("comment_id", ""),
                "content_title": "",
                "content_url": _canonical_url(action.get("content_url") or action.get("url")),
                "comment_url": _canonical_url(action.get("comment_url")),
                "user": action.get("author", ""),
                "author_id": action.get("author_id", ""),
                "author_url": _canonical_url(action.get("author_url")),
                "published_at": action.get("published_at", ""),
                "quote": action.get("quote", ""),
                "locator": {"status": action.get("locator_status", "not_recorded"), "verified_at": action.get("locator_verified_at", "")},
                "quality": _quality_for(action, [row[1] for row in review_rows]),
                "dispatch": [],
            }
            candidate_record["dispatch"].append(action_record)
            record_rows.append(candidate_record)
        else:
            record_rows[match_index]["dispatch"].append(action_record)

    record_rows.sort(key=lambda row: (str(row.get("platform")), str(row.get("candidate_id")), row["record_key"]))
    ledger_bytes = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in record_rows).encode("utf-8")
    screenshot_paths = list(dict.fromkeys(screenshot_paths))
    source_files = _source_list(data_root, prefix, queue_path, results_path, history_path, review_path, candidate_paths, screenshot_paths)
    source_digest = _sha256(json.dumps(source_files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    snapshot_id = _sha256(f"{campaign}\n{revision}\n{source_digest}".encode("utf-8"))[:20]
    qualified_count = sum(row["quality"].get("status") in _QUALIFIED_STATES for row in record_rows)
    author_ids = {
        (row.get("platform"), row.get("author_id"))
        for row in record_rows if row.get("author_id")
    }
    pool_dispatch_statuses = Counter(
        event.get("status", "") for row in record_rows
        if row.get("source_scope") == "locator_candidate" for event in row.get("dispatch", [])
    )
    dispatch_only_statuses = Counter(
        event.get("status", "") for row in record_rows
        if row.get("source_scope") == "dispatch_only" for event in row.get("dispatch", [])
    )
    counts = {
        "candidate_pool_records": len(candidates),
        "ledger_records": len(record_rows),
        "dispatch_only_records": sum(row.get("source_scope") == "dispatch_only" for row in record_rows),
        "dispatch_queue_records": len(queue_rows),
        "dispatch_verified": dispatch_verified,
        "runtime_verified": runtime_verified,
        "paused": sum(count for status, count in action_status_counts.items() if status.startswith("stopped_after")),
        "unique_author_ids": len(author_ids),
        "candidate_pool_unique_author_ids": len({
            (row.get("platform"), row.get("author_id")) for row in record_rows
            if row.get("source_scope") == "locator_candidate" and row.get("author_id")
        }),
        "records_without_author_id": sum(not row.get("author_id") for row in record_rows),
        "quality_reviewed": sum(row["quality"].get("status") != "not_reviewed" for row in record_rows),
        "quality_pending": sum(row["quality"].get("status") not in _RESOLVED_QUALITY_STATES for row in record_rows),
        "candidate_pool_quality_reviewed": sum(
            row["quality"].get("status") != "not_reviewed" for row in record_rows
            if row.get("source_scope") == "locator_candidate"
        ),
        "candidate_pool_unreviewed": sum(
            row["quality"].get("status") == "not_reviewed" for row in record_rows
            if row.get("source_scope") == "locator_candidate"
        ),
        "candidate_pool_quality_pending": sum(
            row["quality"].get("status") not in _RESOLVED_QUALITY_STATES for row in record_rows
            if row.get("source_scope") == "locator_candidate"
        ),
        "dispatch_quality_reviewed": sum(
            bool(row.get("dispatch")) and row["quality"].get("status") != "not_reviewed"
            for row in record_rows
        ),
        "dispatch_quality_unreviewed": sum(
            bool(row.get("dispatch")) and row["quality"].get("status") == "not_reviewed"
            for row in record_rows
        ),
        "dispatch_quality_pending": sum(
            bool(row.get("dispatch")) and row["quality"].get("status") not in _RESOLVED_QUALITY_STATES
            for row in record_rows
        ),
        "qualified": qualified_count,
        "target": int(_CAMPAIGN_TOKEN.search(campaign).group(0)),
        "remaining_gap_to_target": None if any(
            row["quality"].get("status") not in _RESOLVED_QUALITY_STATES for row in record_rows
        ) else max(0, int(_CAMPAIGN_TOKEN.search(campaign).group(0)) - qualified_count),
        "dispatch_statuses": dict(sorted(action_status_counts.items())),
        "candidate_pool_dispatch_statuses": dict(sorted(pool_dispatch_statuses.items())),
        "dispatch_only_statuses": dict(sorted(dispatch_only_statuses.items())),
        "locator_statuses": dict(sorted(Counter(str(row.get("status", "")) for row in candidates).items())),
        "quality_statuses": dict(sorted(Counter(str(row["quality"].get("status", "")) for row in record_rows).items())),
    }
    manifest = {
        "schema_version": 1,
        "campaign": campaign,
        "git_revision": revision,
        "snapshot_id": snapshot_id,
        "candidate_prefix": prefix,
        "queue_path": str(queue_path),
        "results_path": str(results_path) if results_path else "",
        "reply_history_path": str(history_path),
        "quality_review_path": str(review_path) if review_path else "",
        "data_root": str(data_root),
        "counts": counts,
        "ledger_sha256": _sha256(ledger_bytes),
        "source_set_sha256": source_digest,
        "sources": source_files,
        "interpretation": {
            "runtime_verified": "发送结果和 reply_history 对同一平台、URL、作者、回复文本交叉匹配且两方均 submitted=true、verified=true。",
            "qualified": "仅计入质量复核文件明确标为 qualified/qualified_candidate/human_confirmed_qualified 的记录。",
            "identity": "有 author_id 时按平台+author_id 去重；缺少稳定 ID 时不按昵称合并。",
            "target_gap": "候选尚未全部完成质量复核时，剩余目标差额为未定；不以已发送条数或未审条数推算。",
        },
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    snapshot_dir = data_root / "handoff" / campaign / "snapshots" / snapshot_id
    ledger_path = snapshot_dir / "lead-ledger.jsonl"
    manifest_path = snapshot_dir / "manifest.json"
    checksum_path = snapshot_dir / "manifest.sha256"
    if write:
        ledger_created = _write_immutable(ledger_path, ledger_bytes)
        manifest_created = _write_immutable(manifest_path, manifest_bytes)
        checksum_created = _write_immutable(checksum_path, (_sha256(manifest_bytes) + "  manifest.json\n").encode("ascii"))
        reused_existing_snapshot = not (ledger_created or manifest_created or checksum_created)
    else:
        reused_existing_snapshot = False
    return {
        "campaign": campaign,
        "snapshot_id": snapshot_id,
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
        "manifest_sha256": _sha256(manifest_bytes),
        "ledger_sha256": _sha256(ledger_bytes),
        "counts": counts,
        "reused_existing_snapshot": reused_existing_snapshot,
    }
