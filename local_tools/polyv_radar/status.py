from __future__ import annotations

from dataclasses import dataclass


LEAD_STATES = (
    "discovered",
    "evidence_verified",
    "model_reviewed",
    "approved",
    "queued",
    "target_matched",
    "draft_verified",
    "submitted_unverified",
    "submitted_verified",
    "engaged_verified",
)

FAILURE_STATES = {
    "target_not_found",
    "ambiguous",
    "blocked",
    "input_failed",
    "click_failed",
    "post_not_found",
    "page_error",
}

ALLOWED_TRANSITIONS = {
    "": {"discovered", "legacy_unverified"},
    "legacy_unverified": {"discovered", "evidence_verified", "target_not_found", "ambiguous", "blocked"},
    "discovered": {"evidence_verified", "model_reviewed", "target_not_found", "ambiguous"},
    "evidence_verified": {"model_reviewed", "approved", "target_not_found", "ambiguous"},
    "model_reviewed": {"approved", "discovered", "target_not_found", "ambiguous"},
    "approved": {"queued", "discovered", "ambiguous"},
    "queued": {"target_matched", "target_not_found", "ambiguous", "blocked"},
    "target_matched": {"draft_verified", "input_failed", "blocked"},
    "draft_verified": {"submitted_unverified", "input_failed", "blocked"},
    "submitted_unverified": {"submitted_verified", "post_not_found", "click_failed", "blocked"},
    "submitted_verified": {"engaged_verified"},
}


@dataclass(frozen=True)
class Transition:
    old: str
    new: str
    reason: str = ""


def is_known_state(value: str) -> bool:
    return value in LEAD_STATES or value in FAILURE_STATES or value in {"legacy_unverified", "legacy_rejected", ""}


def validate_transition(old: str, new: str) -> None:
    if not is_known_state(old) or not is_known_state(new):
        raise ValueError(f"未知线索状态: {old!r} -> {new!r}")
    if new in FAILURE_STATES:
        if old not in {"queued", "target_matched", "draft_verified", "submitted_unverified", "legacy_unverified", "discovered", "evidence_verified", "model_reviewed", "approved"}:
            raise ValueError(f"不允许从 {old} 进入失败状态 {new}")
        return
    if new not in ALLOWED_TRANSITIONS.get(old, set()):
        raise ValueError(f"不允许的线索状态迁移: {old or '<empty>'} -> {new}")


def transition(old: str, new: str, reason: str = "") -> Transition:
    validate_transition(old, new)
    return Transition(old, new, reason)
