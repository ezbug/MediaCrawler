from __future__ import annotations

import re
from collections import OrderedDict
from typing import Iterable

from .models import LeadEvidence


_COMPANY_RE = re.compile(
    r"(?P<company>[^|｜\n]{2,40}(?:公司|集团|证券|银行|科技|教育|大学|医院|研究院|基金|保险|传媒|制造|股份|有限))"
)
_ROLE_RE = re.compile(r"(?P<role>[^|｜\n]{2,30}(?:负责人|总监|经理|主管|专员|顾问|架构师|工程师|老师|主任))")


def extract_company_role(text: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    company_match = _COMPANY_RE.search(text)
    role_match = _ROLE_RE.search(text)
    company = company_match.group("company").strip(" ·|｜") if company_match else ""
    role = role_match.group("role").strip(" ·|｜") if role_match else ""
    return company, role


def classify_identity_confidence(company: str, role: str, external_urls: Iterable[str]) -> str:
    has_external = any(str(url).strip() for url in external_urls)
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
