from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromotionRule:
    min_total_return: float = 0.02
    max_drawdown_floor: float = -0.2
    min_trade_count: int = 1
    require_baseline_passed: bool = True


@dataclass(frozen=True)
class PromotionDecision:
    accepted: bool
    status: str
    reasons: tuple[str, ...]
    evidence: dict[str, Any]


def evaluate_strategy_promotion(record: dict[str, Any], rule: PromotionRule | None = None) -> PromotionDecision:
    rule = rule or PromotionRule()
    candidate = dict(record.get("candidate") or {})
    metrics = dict(candidate.get("metrics") or {})
    comparison = dict(candidate.get("comparison") or {})
    reasons: list[str] = []

    total_return = float(metrics.get("total_return") or 0)
    max_drawdown = float(metrics.get("max_drawdown") or 0)
    trade_count = int(metrics.get("trade_count") or 0)
    baseline_passed = bool(comparison.get("passed"))

    if total_return < rule.min_total_return:
        reasons.append("total_return_below_minimum")
    if max_drawdown < rule.max_drawdown_floor:
        reasons.append("max_drawdown_too_deep")
    if trade_count < rule.min_trade_count:
        reasons.append("trade_count_too_low")
    if rule.require_baseline_passed and not baseline_passed:
        reasons.append("baseline_not_cleared")

    accepted = not reasons
    return PromotionDecision(
        accepted=accepted,
        status="accepted_for_paper_observation" if accepted else "rejected",
        reasons=tuple(reasons),
        evidence={
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "trade_count": trade_count,
            "baseline_passed": baseline_passed,
            "rule": rule.__dict__,
        },
    )


def promotion_decision_payload(decision: PromotionDecision) -> dict[str, Any]:
    return {
        "accepted": decision.accepted,
        "status": decision.status,
        "reasons": list(decision.reasons),
        "evidence": decision.evidence,
    }


def promotion_summary(records: list[dict[str, Any]], rule: PromotionRule | None = None) -> dict[str, Any]:
    decisions = [evaluate_strategy_promotion(record, rule) for record in records]
    accepted = [decision for decision in decisions if decision.accepted]
    reason_counts: dict[str, int] = {}
    for decision in decisions:
        for reason in decision.reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "candidate_count": len(records),
        "accepted_count": len(accepted),
        "rejected_count": len(records) - len(accepted),
        "reason_counts": dict(sorted(reason_counts.items())),
        "decisions": [promotion_decision_payload(decision) for decision in decisions],
    }
