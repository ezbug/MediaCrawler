from __future__ import annotations

import json
import os
import re
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import RadarConfig
from .models import ExternalEvidence, LeadEvidence, ProfilePost, ProfileSnapshot
from .storage import RadarStore


_COMPANY_RE = re.compile(
    r"(?P<company>[^|｜\n]{2,40}(?:公司|集团|证券|银行|科技|教育|大学|医院|研究院|基金|保险|传媒|制造|股份|有限))"
)
_ROLE_RE = re.compile(r"(?P<role>[^|｜\n]{2,30}(?:负责人|总监|经理|主管|专员|顾问|架构师|工程师|老师|主任))")
_PROFILE_FOOTER_TERMS = (
    "ICP备案", "营业执照", "增值电信", "网络文化经营许可证", "公网安备", "违法不良信息举报",
    "互联网药品信息", "医疗器械网络交易", "地址:", "电话:", "版权所有", "行吟信息科技",
)


def _clean_profile_text(text: str) -> str:
    lines = []
    for line in re.split(r"[\n|｜]+", text or ""):
        line = re.sub(r"\s+", " ", line).strip()
        if line and not any(term.casefold() in line.casefold() for term in _PROFILE_FOOTER_TERMS):
            lines.append(line)
    return "｜".join(lines)


def extract_company_role(text: str) -> tuple[str, str]:
    text = _clean_profile_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    company_match = _COMPANY_RE.search(text)
    role_match = _ROLE_RE.search(text)
    company = company_match.group("company").strip(" ·|｜") if company_match else ""
    role = role_match.group("role").strip(" ·|｜") if role_match else ""
    return company, role


def classify_identity_confidence(
    company: str,
    role: str,
    external_urls: Iterable[str],
    verified: bool = False,
) -> str:
    has_external = any(str(url).strip() for url in external_urls)
    if verified:
        return "high"
    if company and role and has_external:
        return "high"
    if company or role:
        return "medium"
    return "low"


def choose_enrichment_candidates(leads: Iterable[LeadEvidence], limit: int = 50) -> list[LeadEvidence]:
    selected: OrderedDict[str, LeadEvidence] = OrderedDict()
    ranked = sorted(leads, key=lambda item: (-item.score, item.platform, item.content_id, item.comment_id))
    for lead in ranked:
        identity = lead.author_id or f"{lead.platform}:{lead.profile_url or lead.user}"
        if identity not in selected:
            selected[identity] = lead
        if len(selected) >= limit:
            break
    return list(selected.values())


def _run_ego_json_script(
    script_path: Path,
    input_path: Path,
    output_path: Path,
    input_var: str,
    output_var: str,
    taskspace: int | None = None,
    runner=subprocess.run,
) -> tuple[bool, str]:
    if taskspace is None:
        if runner is subprocess.run:
            raise ValueError("主页/站外调查必须显式提供用户已登录的 Ego Lite TaskSpace")
        taskspace = 1  # test doubles never open a browser; production CLI is explicit
    launcher = (
        f"process.env.{input_var} = {json.dumps(str(input_path))};\n"
        f"process.env.{output_var} = {json.dumps(str(output_path))};\n"
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
            timeout=240,
            cwd=script_path.resolve().parents[2],
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return result.returncode == 0 and output_path.exists(), (result.stderr or result.stdout or "").strip()[-1000:]


def run_profile_enrichment(
    config: RadarConfig,
    repo_root: Path,
    run_id: str,
    leads: Iterable[LeadEvidence],
    taskspace: int | None = None,
    runner=subprocess.run,
) -> dict[str, int | str]:
    selected = [item for item in choose_enrichment_candidates(leads) if item.author_id and item.profile_url]
    if not selected:
        return {"profiles": 0, "posts": 0, "external_evidence": 0, "status": "no_profile_identifiers"}
    enrichment_root = config.data_root / "enrichment" / run_id
    enrichment_root.mkdir(parents=True, exist_ok=True)
    input_path = enrichment_root / "profiles-input.json"
    output_path = enrichment_root / "profiles-output.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "run_id": run_id,
                    "platform": item.platform,
                    "author_id": item.author_id,
                    "profile_url": item.profile_url,
                    "user": item.user,
                    "quote": item.quote,
                    "event_type": item.event_type,
                }
                for item in selected
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile_ok, profile_log = _run_ego_json_script(
        repo_root / "local_tools" / "polyv_radar" / "ego_profile_enricher.mjs",
        input_path,
        output_path,
        "POLYV_PROFILE_INPUT",
        "POLYV_PROFILE_OUTPUT",
        taskspace=taskspace,
        runner=runner,
    )
    if not profile_ok:
        return {"profiles": 0, "posts": 0, "external_evidence": 0, "status": "profile_failed", "log": profile_log}

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles", [])
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    store.clear_enrichment(run_id)
    web_candidates = []
    profile_count = 0
    post_count = 0
    for raw in profiles:
        if raw.get("available") is False or raw.get("error"):
            continue
        bio = str(raw.get("bio", ""))
        company, role = extract_company_role(f"{raw.get('display_name', '')}\n{bio}")
        identity_confidence = classify_identity_confidence(company, role, [], bool(raw.get("verified")))
        profile = ProfileSnapshot(
            run_id=run_id,
            platform=str(raw.get("platform", "")),
            author_id=str(raw.get("author_id", "")),
            author_url=str(raw.get("author_url", "")),
            display_name=str(raw.get("display_name", "")),
            bio=bio,
            verified=bool(raw.get("verified")),
            company=company,
            role=role,
            identity_confidence=identity_confidence,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
        if not profile.author_id:
            continue
        store.upsert_profile(profile)
        profile_count += 1
        for post in raw.get("posts", [])[:5]:
            store.upsert_profile_post(
                ProfilePost(
                    run_id=run_id,
                    platform=profile.platform,
                    author_id=profile.author_id,
                    post_id=str(post.get("post_id", "")),
                    url=str(post.get("url", "")),
                    title=str(post.get("title", "")),
                    text=str(post.get("text", "")),
                    published_at=str(post.get("published_at", "")),
                )
            )
            post_count += 1
        if company:
            web_candidates.append(
                {
                    "run_id": run_id,
                    "platform": profile.platform,
                    "author_id": profile.author_id,
                    "company": company,
                    "quote": next((item.quote for item in selected if item.author_id == profile.author_id), ""),
                    "event_type": next((item.event_type for item in selected if item.author_id == profile.author_id), ""),
                }
            )

    web_count = 0
    external_urls_by_author: dict[tuple[str, str], set[str]] = {}
    if web_candidates:
        web_input = enrichment_root / "web-input.json"
        web_output = enrichment_root / "web-output.json"
        web_input.write_text(json.dumps(web_candidates, ensure_ascii=False), encoding="utf-8")
        web_ok, web_log = _run_ego_json_script(
            repo_root / "local_tools" / "polyv_radar" / "ego_web_search.mjs",
            web_input,
            web_output,
            "POLYV_WEB_INPUT",
            "POLYV_WEB_OUTPUT",
            taskspace=taskspace,
            runner=runner,
        )
        if web_ok:
            for raw in json.loads(web_output.read_text(encoding="utf-8")).get("evidence", [])[: len(web_candidates) * 5]:
                source_url = str(raw.get("source_url", ""))
                if not source_url:
                    continue
                store.upsert_external_evidence(
                    ExternalEvidence(
                        run_id=run_id,
                        platform=str(raw.get("platform", "")),
                        author_id=str(raw.get("author_id", "")),
                        source_url=source_url,
                        source_type=str(raw.get("source_type", "public_web")),
                        title=str(raw.get("title", "")),
                        snippet=str(raw.get("snippet", "")),
                        published_at=str(raw.get("published_at", "")),
                        match_confidence="medium",
                    )
                )
                external_urls_by_author.setdefault(
                    (str(raw.get("platform", "")), str(raw.get("author_id", ""))), set()
                ).add(source_url)
                web_count += 1
    for profile in profiles:
        platform = str(profile.get("platform", ""))
        author_id = str(profile.get("author_id", ""))
        urls = external_urls_by_author.get((platform, author_id), set())
        if not author_id or not urls:
            continue
        company, role = extract_company_role(
            f"{profile.get('display_name', '')}\n{profile.get('bio', '')}"
        )
        store.update_profile_identity(
            run_id,
            platform,
            author_id,
            classify_identity_confidence(company, role, urls, bool(profile.get("verified"))),
            urls,
        )
    store.close()
    return {"profiles": profile_count, "posts": post_count, "external_evidence": web_count, "status": "success"}
