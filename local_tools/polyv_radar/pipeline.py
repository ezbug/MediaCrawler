from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .config import RadarConfig
from .enrichment import choose_enrichment_candidates, run_profile_enrichment
from .models import CommentRecord, ContentRecord, LeadAssessment, LeadEvidence
from .review import run_codex_review
from .scoring import SOLUTIONS, classify_category, score_purchase_evidence
from .storage import RadarStore


def _key(value: str) -> str:
    return "".join(str(value or "").casefold().split())


def _lead_from_score(content: ContentRecord, comment: CommentRecord | None, result) -> LeadEvidence:
    quote = comment.text if comment else content.text
    profile_url = (comment.author_url if comment else "") or content.creator_url or content.author_url
    author_id = (comment.author_id if comment else "") or content.author_id
    category = classify_category(f"{content.title}\n{content.text}", None)
    reasons = [f"{name}:{value}" for name, value in result.dimensions.items() if value]
    return LeadEvidence(
        platform=content.platform,
        content_id=content.content_id,
        comment_id=comment.comment_id if comment else "",
        url=content.url,
        user=comment.author if comment else content.author,
        quote=quote,
        category=category,
        solution=SOLUTIONS.get(category, SOLUTIONS["未分类"]),
        score=result.score,
        reasons=reasons,
        evidence_sentences=result.evidence_sentences,
        outreach="公开答疑，并明确说明POLYV身份",
        content_title=content.title,
        event_type=result.event_type,
        profile_url=profile_url,
        author_url=profile_url,
        dimensions=result.dimensions,
        stage="prefilter",
        rejection_reason=result.rejected_reason,
        author_id=author_id,
    )


def build_prefilter_leads(
    contents: Iterable[ContentRecord],
    comments: Iterable[CommentRecord],
    max_candidates: int = 50,
    now: datetime | None = None,
    min_score: int = 4,
    excluded_author_names: Iterable[str] = (),
) -> list[LeadEvidence]:
    content_by_key = {(item.platform, item.content_id): item for item in contents}
    comments_by_content: dict[tuple[str, str], list[CommentRecord]] = defaultdict(list)
    for comment in comments:
        comments_by_content[(comment.platform, comment.content_id)].append(comment)

    best: dict[tuple[str, str, str], LeadEvidence] = {}
    excluded = tuple(item.casefold() for item in excluded_author_names if item)
    for key, content in content_by_key.items():
        related = comments_by_content.get(key, [])
        records = [(content, comment) for comment in related] or [(content, None)]
        for item, comment in records:
            author_name = (comment.author if comment else content.author).casefold()
            if any(token in author_name for token in excluded):
                continue
            result = score_purchase_evidence(item, comment, now=now)
            if result.score < min_score:
                continue
            lead = _lead_from_score(item, comment, result)
            identity = lead.author_id or lead.profile_url or lead.user
            dedupe_key = (lead.platform, _key(identity), _key(lead.quote))
            existing = best.get(dedupe_key)
            if existing is None or lead.score > existing.score:
                best[dedupe_key] = lead

    return sorted(best.values(), key=lambda item: (-item.score, item.platform, item.content_id, item.comment_id))[:max_candidates]


def candidate_bundle(store: RadarStore, run_id: str, leads: Iterable[LeadEvidence]) -> list[dict]:
    profiles = {(row["platform"], row["author_id"]): row for row in store.load_profiles(run_id)}
    posts_by_author: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in store.load_profile_posts(run_id):
        posts_by_author[(row["platform"], row["author_id"])].append(row)
    evidence_by_author: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in store.load_external_evidence(run_id):
        evidence_by_author[(row["platform"], row["author_id"])].append(row)
    bundle = []
    for lead in leads:
        profile = profiles.get((lead.platform, lead.author_id), {})
        sources = [{"url": lead.url, "type": "content", "text": lead.quote}]
        if lead.profile_url:
            sources.append({"url": lead.profile_url, "type": "profile", "text": profile.get("bio", "")})
        for item in posts_by_author.get((lead.platform, lead.author_id), [])[:5]:
            if item.get("url"):
                sources.append(
                    {
                        "url": item["url"],
                        "type": "profile_post",
                        "text": item.get("text", "") or item.get("title", ""),
                    }
                )
        for item in evidence_by_author.get((lead.platform, lead.author_id), []):
            sources.append({"url": item["source_url"], "type": item["source_type"], "text": item["snippet"]})
        bundle.append(
            {
                "run_id": run_id,
                "platform": lead.platform,
                "content_id": lead.content_id,
                "comment_id": lead.comment_id,
                "user": lead.user,
                "author_id": lead.author_id,
                "quote": lead.quote,
                "content_title": lead.content_title,
                "event_type": lead.event_type,
                "profile_url": lead.profile_url,
                "profile": {
                    "display_name": profile.get("display_name", ""),
                    "bio": profile.get("bio", ""),
                    "company": profile.get("company", ""),
                    "role": profile.get("role", ""),
                    "identity_confidence": profile.get("identity_confidence", "low"),
                },
                "sources": sources,
            }
        )
    return bundle


def prefilter_store(config: RadarConfig, run_id: str, max_candidates: int = 50) -> list[LeadEvidence]:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = build_prefilter_leads(
        store.iter_contents(run_id),
        store.iter_comments(run_id),
        max_candidates=max_candidates,
        min_score=config.min_lead_score,
        excluded_author_names=config.excluded_author_names,
    )
    store.save_leads(run_id, leads)
    path = config.data_root / "review" / f"{run_id}-prefilter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([lead.to_dict() for lead in leads], ensure_ascii=False, indent=2), encoding="utf-8")
    store.close()
    return leads


def enrich_store(config: RadarConfig, repo_root: Path, run_id: str) -> dict:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    store.close()
    return run_profile_enrichment(config, repo_root, run_id, choose_enrichment_candidates(leads))


def review_store(
    config: RadarConfig,
    run_id: str,
    codex: str = "codex",
    runner: Callable = None,
) -> dict[str, int]:
    store = RadarStore(config.data_root / "radar.sqlite3")
    store.initialize()
    leads = store.load_leads(run_id)
    bundle = candidate_bundle(store, run_id, leads)
    profiles = {(row["platform"], row["author_id"]): row for row in store.load_profiles(run_id)}
    assessments = []
    reviewed: list[LeadEvidence] = []
    stats = {"high_value": 0, "review": 0, "rejected": 0, "model_fallback": 0}
    for lead, candidate in zip(leads, bundle):
        payload, status = run_codex_review(candidate, codex=codex, runner=runner or __import__("subprocess").run)
        profile = profiles.get((lead.platform, lead.author_id), {})
        if payload is None:
            stats["model_fallback"] += 1
            assessment = LeadAssessment(
                run_id=run_id,
                platform=lead.platform,
                content_id=lead.content_id,
                comment_id=lead.comment_id,
                score=lead.score,
                dimensions=lead.dimensions,
                event_type=lead.event_type,
                identity_confidence=profile.get("identity_confidence", "low"),
                evidence=[{"dimension": "rule", "quote": lead.quote, "url": lead.url}],
                decision="review",
                reason="模型复核未完成，保留规则结果并要求人工核验",
                model_status=status,
            )
            reviewed_lead = LeadEvidence(
                **{
                    **lead.to_dict(),
                    "stage": "model_fallback",
                    "decision": "review",
                    "identity_confidence": profile.get("identity_confidence", "low"),
                }
            )
        else:
            assessment = LeadAssessment(
                run_id=run_id,
                platform=lead.platform,
                content_id=lead.content_id,
                comment_id=lead.comment_id,
                score=payload["score"],
                dimensions=payload["dimensions"],
                event_type=payload["event_type"],
                identity_confidence=payload["identity_confidence"],
                evidence=payload["evidence"],
                decision=payload["decision"],
                reason=payload["reason"],
                model_status=status,
            )
            reviewed_lead = LeadEvidence(
                **{
                    **lead.to_dict(),
                    "score": payload["score"],
                    "dimensions": payload["dimensions"],
                    "event_type": payload["event_type"],
                    "identity_confidence": payload["identity_confidence"],
                    "evidence_urls": [item["url"] for item in payload["evidence"]],
                    "rejection_reason": "" if payload["decision"] != "reject" else payload["reason"],
                    "stage": "model_rejected" if payload["decision"] == "reject" else "model_reviewed",
                    "decision": payload["decision"],
                }
            )
        if assessment.decision == "high_value" and assessment.score >= config.min_lead_score:
            stats["high_value"] += 1
        elif assessment.decision == "review":
            stats["review"] += 1
        else:
            stats["rejected"] += 1
        assessments.append(assessment)
        reviewed.append(reviewed_lead)
    store.save_assessments(assessments)
    store.save_leads(run_id, reviewed)
    store.close()
    return stats
