from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import subprocess
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


VENDOR_PROFILE_TERMS = (
    "服务商", "供应商", "服务系统", "云直播", "直播服务", "一站式会务", "会展公司", "影像服务",
    "软件平台", "考培系统", "商学园", "酷学院", "咨询师", "培训顾问", "咨询公司", "我们提供",
    "欢迎交流", "欢迎咨询", "解决方案提供", "专注企业直播",
)
VENDOR_NAME_TERMS = ("云直播", "直播服务", "会展", "影像", "商学园", "酷学院", "考培系统", "直播平台")
VENDOR_EXCLUSION_REASON = "主页或身份信息显示为服务商、平台方或咨询/会展账号"
BUYER_SIGNAL_TERMS = (
    "我们公司", "我司", "公司要", "企业要", "公司需要", "企业需要", "正在找", "在找", "求推荐", "求平台",
    "多少钱", "报价", "采购", "选型", "供应商", "服务商", "求方案", "征集", "老板让我", "下个月", "本月", "近期", "准备", "筹备",
    "正在做", "需要", "想找", "用什么", "哪家", "能不能支持",
)
EDITORIAL_TERMS = ("攻略", "指南", "避坑", "解析", "案例", "经验分享", "保姆级", "干货")
GENERIC_AUTHOR_NAMES = ("知乎答主", "知乎用户", "B站创作者", "B站用户", "抖音创作者", "小红书用户")


def normalize_locator_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


@dataclass(frozen=True)
class LocatorResult:
    status: str
    index: int | None = None
    method: str = ""
    reason: str = ""


def locate_comment(
    comments: Iterable[dict],
    author: str,
    quote: str,
    native_comment_id: str = "",
    parent_comment_id: str = "",
) -> LocatorResult:
    rows = list(comments)
    expected_author = normalize_locator_text(author)
    expected_quote = normalize_locator_text(quote)
    matches: list[tuple[int, str]] = []
    for index, item in enumerate(rows):
        item_author = normalize_locator_text(item.get("author", ""))
        item_quote = normalize_locator_text(item.get("text", item.get("quote", "")))
        if native_comment_id and str(item.get("native_comment_id", "")) == native_comment_id:
            matches.append((index, "native_id"))
        elif item_author == expected_author and item_quote == expected_quote:
            matches.append((index, "author_quote"))

    if parent_comment_id:
        parent_matches = [
            item for item in matches
            if str(rows[item[0]].get("parent_comment_id", "")) == str(parent_comment_id)
            or str(rows[item[0]].get("native_parent_id", "")) == str(parent_comment_id)
        ]
        if parent_matches:
            matches = parent_matches
    if len(matches) == 1:
        index, method = matches[0]
        return LocatorResult("verified", index, method, "作者和原话唯一匹配")
    if len(matches) > 1:
        return LocatorResult("ambiguous", reason="作者和原话匹配多个评论")
    return LocatorResult("not_found", reason="页面中未找到对应作者和原话")


@dataclass(frozen=True)
class LocatorUrl:
    url: str
    method: str


def locator_url(
    platform: str,
    content_url: str,
    native_comment_id: str = "",
    comment_url: str = "",
    verified: bool = False,
) -> LocatorUrl:
    if verified and comment_url:
        return LocatorUrl(comment_url, "direct_url")
    if verified and platform == "bili" and native_comment_id:
        parts = urlsplit(content_url)
        return LocatorUrl(
            urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, f"reply{native_comment_id}")),
            "native_id",
        )
    return LocatorUrl(content_url, "author_quote")


def _candidate_key(item: dict) -> str:
    return ":".join(
        str(item.get(name, ""))
        for name in ("run_id", "platform", "content_id", "comment_id")
    )


def _lead_candidate_key(run_id: str, lead) -> str:
    return _candidate_key({"run_id": run_id, **lead.to_dict()})


def _read_locator_results(output_path: Path) -> tuple[list[dict], str]:
    if not output_path.exists():
        return [], ""
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"Ego Lite定位结果解析失败: {exc}"
    results = payload.get("results", [])
    if not isinstance(results, list):
        return [], "Ego Lite定位结果格式无效"
    return [item for item in results if isinstance(item, dict)], ""


def _merge_locator_results(
    rows: list[dict], checked_rows: list[dict], reason: str = ""
) -> tuple[dict[str, dict], str]:
    checked = {_candidate_key(item): item for item in checked_rows}
    fallback_reason = reason or "Ego Lite未返回该候选结果"
    merged = {
        _candidate_key(row): checked.get(
            _candidate_key(row),
            {
                **row,
                "status": "error",
                "reason": fallback_reason,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        for row in rows
    }
    return merged, reason


def run_ego_locator(
    candidates: Iterable[dict],
    repo_root: Path,
    work_dir: Path,
    taskspace: int | None = None,
    runner=subprocess.run,
    timeout: int = 240,
) -> tuple[dict[str, dict], str]:
    rows = list(candidates)
    if not rows:
        return {}, ""
    if taskspace is None:
        if runner is subprocess.run:
            raise ValueError("定位必须显式提供用户已登录的 Ego Lite TaskSpace")
        taskspace = 1  # test doubles never open a browser; production CLI is explicit
    if int(taskspace) <= 0:
        raise ValueError("定位必须显式提供用户已登录的 Ego Lite TaskSpace")
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "locator-input.json"
    output_path = work_dir / "locator-output.json"
    input_path.write_text(json.dumps({"candidates": rows}, ensure_ascii=False), encoding="utf-8")
    script_path = repo_root / "local_tools" / "polyv_radar" / "ego_comment_locator.mjs"
    launcher = (
        f"process.env.POLYV_LOCATOR_INPUT = {json.dumps(str(input_path))};\n"
        f"process.env.POLYV_LOCATOR_OUTPUT = {json.dumps(str(output_path))};\n"
        f"process.env.POLYV_TASKSPACE_ID = {json.dumps(str(taskspace))};\n"
        f"await import({json.dumps(str(script_path))});\n"
    )
    try:
        result = runner(
            ["ego-browser", "nodejs"],
            input=launcher,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            cwd=repo_root,
        )
    except subprocess.TimeoutExpired as exc:
        checked_rows, parse_log = _read_locator_results(output_path)
        return _merge_locator_results(
            rows,
            checked_rows,
            parse_log or f"Ego Lite定位超时（已保留已完成结果）: {exc}",
        )
    except OSError as exc:
        return _merge_locator_results(rows, [], f"Ego Lite定位失败: {exc}")
    results, parse_log = _read_locator_results(output_path)
    process_log = (result.stderr or result.stdout or "").strip()[-1000:]
    if result.returncode != 0:
        process_log = process_log or "Ego Lite定位进程异常退出"
        if parse_log:
            process_log = f"{process_log}; {parse_log}"
    return _merge_locator_results(rows, results, process_log if result.returncode != 0 else parse_log)


def is_deliverable_lead(lead, min_score: int = 4) -> bool:
    dimensions = lead.dimensions or {}
    has_business_scene = int(dimensions.get("business_scene", 0) or 0) > 0
    has_project_selection_or_delivery = (
        int(dimensions.get("project_timing", 0) or 0) > 0
        or int(dimensions.get("platform_intent", 0) or 0) > 0
        or int(dimensions.get("delivery_inquiry", 0) or 0) > 0
    )
    return (
        lead.score >= min_score
        and lead.locator_status == "verified"
        and lead.decision != "reject"
        and not lead_exclusion_reason(lead)
        and has_business_scene
        and has_project_selection_or_delivery
    )


def lead_exclusion_reason(lead) -> str:
    if normalize_locator_text(lead.user) in {normalize_locator_text(item) for item in GENERIC_AUTHOR_NAMES}:
        return "作者是平台泛化占位名，无法完成身份核验"
    profile_text = " ".join(
        str(value or "")
        for value in (lead.user, lead.company, lead.role, lead.profile_bio)
    ).casefold()
    if any(term.casefold() in profile_text for term in VENDOR_PROFILE_TERMS):
        return VENDOR_EXCLUSION_REASON
    if any(term.casefold() in str(lead.user or "").casefold() for term in VENDOR_NAME_TERMS):
        return "用户名显示为直播、软件或会展服务账号"
    signal_text = f"{lead.content_title}\n{lead.quote}".casefold()
    has_buyer_signal = any(term.casefold() in signal_text for term in BUYER_SIGNAL_TERMS)
    if not has_buyer_signal:
        return "原文缺少第一人称需求或明确采购/项目询问"
    editorial_terms = (*EDITORIAL_TERMS, "选型", "评测", "推荐")
    if lead.source_type in {"post", "answer", "content"} and any(
        term.casefold() in signal_text for term in editorial_terms
    ) and not any(term.casefold() in str(lead.quote or "").casefold() for term in ("我们公司", "我司", "公司要", "公司需要", "企业要", "企业需要")):
        return "内容为攻略、指南或案例型发布，缺少第一人称项目需求"
    return ""


def select_deliverable_leads(leads: Iterable, target: int, min_score: int = 4) -> list:
    selected = []
    seen_identities: set[str] = set()
    seen_companies: set[str] = set()
    ranked = sorted(leads, key=lambda item: (-item.score, item.platform, item.content_id, item.comment_id))
    for lead in ranked:
        if not is_deliverable_lead(lead, min_score):
            continue
        identity = lead.author_id or lead.profile_url or f"{lead.platform}:{lead.user}"
        identity_key = normalize_locator_text(identity)
        if not identity_key or identity_key in seen_identities:
            continue
        company_key = normalize_locator_text(lead.company)
        if company_key and company_key in seen_companies:
            continue
        seen_identities.add(identity_key)
        if company_key:
            seen_companies.add(company_key)
        selected.append(lead)
        if len(selected) >= max(0, target):
            break
    return selected


def locate_store(
    config,
    repo_root: Path,
    run_id: str,
    max_candidates: int = 80,
    taskspace: int | None = None,
    runner=subprocess.run,
) -> dict[str, int | str]:
    from .storage import RadarStore

    if taskspace is None:
        if runner is subprocess.run:
            raise ValueError("locate 必须显式传入 --taskspace；不使用固定会话")
        taskspace = 1  # test doubles never open a browser; production CLI is explicit
    if int(taskspace) <= 0:
        raise ValueError("locate 必须显式传入 --taskspace；不使用固定会话")

    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    all_leads = store.load_leads(run_id)
    leads = [lead for lead in all_leads if lead.score >= config.min_lead_score and lead.decision != "reject"][:max_candidates]
    candidates = [
        {
            "run_id": run_id,
            "platform": lead.platform,
            "content_id": lead.content_id,
            "comment_id": lead.comment_id,
            "source_type": lead.source_type,
            "content_url": lead.url,
            "comment_url": lead.comment_url,
            "user": lead.user,
            "author_id": lead.author_id,
            "quote": lead.quote,
            "native_comment_id": lead.native_comment_id,
            "parent_comment_id": lead.parent_comment_id,
        }
        for lead in leads
    ]
    results, log = run_ego_locator(
        candidates,
        repo_root,
        config.data_root / "locators" / run_id,
        taskspace=taskspace,
        runner=runner,
    )
    store.clear_comment_locators(run_id)
    updated = []
    for lead in leads:
        result = results.get(
            _lead_candidate_key(run_id, lead),
            {"status": "error", "reason": "Ego Lite未返回该候选结果"},
        )
        locator_url_value = str(result.get("locator_url") or lead.comment_url or (lead.url if lead.source_type in {"post", "answer", "content"} else ""))
        locator_status = str(result.get("status", "error"))
        verified_at = str(result.get("verified_at", datetime.now(timezone.utc).isoformat()))
        updated_lead = type(lead)(
            **{
                **lead.to_dict(),
                "comment_url": locator_url_value,
                "locator_status": locator_status,
                "locator_method": str(result.get("locator_method", "")),
                "locator_verified_at": verified_at if locator_status == "verified" else "",
                "locator_reason": str(result.get("reason", "")),
            }
        )
        updated.append(updated_lead)
        store.save_comment_locator(
            {
                "run_id": run_id,
                "platform": lead.platform,
                "content_id": lead.content_id,
                "comment_id": lead.comment_id,
                "source_type": lead.source_type,
                "content_url": lead.url,
                "comment_url": locator_url_value,
                "locator_method": updated_lead.locator_method,
                "status": locator_status,
                "native_comment_id": lead.native_comment_id,
                "native_parent_id": lead.parent_comment_id,
                "matched_author": str(result.get("matched_author", "")),
                "matched_quote": str(result.get("matched_quote", "")),
                "final_url": str(result.get("final_url", "")),
                "reason": updated_lead.locator_reason,
                "screenshot_path": str(result.get("screenshot_path", "")),
                "verified_at": verified_at,
            }
        )
    updated_by_key = {
        (lead.platform, lead.content_id, lead.comment_id): lead
        for lead in updated
    }
    store.save_leads(
        run_id,
        [
            updated_by_key.get((lead.platform, lead.content_id, lead.comment_id), lead)
            for lead in all_leads
        ],
    )
    store.close()
    counts: dict[str, int | str] = {"candidates": len(leads), "verified": 0, "not_found": 0, "blocked": 0, "ambiguous": 0, "error": 0}
    for lead in updated:
        counts[lead.locator_status] = int(counts.get(lead.locator_status, 0)) + 1
    if log:
        counts["log"] = log
    return counts
