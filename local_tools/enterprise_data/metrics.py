"""计算规则：增长率、口径可比性、规模分层与招聘活动指数。"""
from __future__ import annotations

MISSING = "missing"
ZERO_BASE = "zero_base"
GROWTH_OK = "ok"
COMPARABLE = "comparable"
NOT_COMPARABLE = "not_comparable"

EMPLOYEE_TIERS = ((1000, "LARGE"), (100, "MEDIUM"), (10, "SMALL"), (1, "MICRO"))
ASSET_TIERS = ((500_000_000, "LARGE"), (50_000_000, "MEDIUM"), (5_000_000, "SMALL"), (1, "MICRO"))

#: 招聘活动指数权重（设计文档 5.4）
HIRING_WEIGHTS = {
    "new_jobs": 0.30,
    "explicit_slots": 0.25,
    "activity": 0.20,
    "platform_breadth": 0.15,
    "diversity": 0.10,
}


def growth_rate(current: float | int | None, previous: float | int | None) -> tuple[float | None, str]:
    """返回 (增长率, 状态)。上年为 0 记 zero_base，缺值记 missing。"""
    if current is None or previous is None:
        return None, MISSING
    if previous == 0:
        return None, ZERO_BASE
    return (current - previous) / previous, GROWTH_OK


def check_comparability(
    *,
    scope_now: str | None,
    scope_prev: str | None,
    type_now: str | None,
    type_prev: str | None,
) -> str:
    """口径可比性：统计范围或统计类型不一致时不允许计算正式同比。"""
    if not scope_now or not scope_prev:
        return NOT_COMPARABLE
    if scope_now != scope_prev:
        return NOT_COMPARABLE
    if (type_now or "") != (type_prev or ""):
        return NOT_COMPARABLE
    return COMPARABLE


def size_by_employee(count: int | None) -> str | None:
    if count is None or count <= 0:
        return None
    for threshold, label in EMPLOYEE_TIERS:
        if count >= threshold:
            return label
    return None


def size_by_assets(amount: float | None) -> str | None:
    if amount is None or amount <= 0:
        return None
    for threshold, label in ASSET_TIERS:
        if amount >= threshold:
            return label
    return None


def hiring_activity_score(subscores: dict[str, float | None]) -> tuple[float | None, dict]:
    """0-100 招聘活动指数。缺失维度不按 0 计，而是重新归一化权重。"""
    available = {key: value for key, value in subscores.items() if value is not None and key in HIRING_WEIGHTS}
    if not available:
        return None, {"used_weights": {}, "missing": sorted(set(HIRING_WEIGHTS) - set(available))}
    total_weight = sum(HIRING_WEIGHTS[key] for key in available)
    score = sum(min(max(float(value), 0.0), 100.0) * HIRING_WEIGHTS[key] for key, value in available.items()) / total_weight
    return round(score, 2), {
        "used_weights": {key: round(HIRING_WEIGHTS[key] / total_weight, 4) for key in available},
        "missing": sorted(set(HIRING_WEIGHTS) - set(available)),
    }


def job_staleness_label(*, age_days: float | None, times_seen: int = 1, republished: bool = False, outsourcing_hint: bool = False, closed: bool = False) -> str:
    """职位状态标签：仅作风险信号，不直接删除记录。"""
    if closed:
        return "CLOSED_OR_UNAVAILABLE"
    if republished:
        return "REPUBLISHED"
    if outsourcing_hint:
        return "POSSIBLE_OUTSOURCING"
    if age_days is not None and age_days >= 60 and times_seen >= 2:
        return "LONG_RUNNING"
    if age_days is not None and age_days >= 60:
        return "POSSIBLE_STALE"
    return "active"
