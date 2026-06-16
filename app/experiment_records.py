from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.parameter_search import ParameterSearchResult, search_result_payload


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    name: str
    status: str
    candidate: dict[str, Any]
    baseline: dict[str, Any] | None
    decision: str
    created_at: str


def compare_candidate_to_baseline(candidate: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate_metrics = dict(candidate.get("metrics") or {})
    baseline_metrics = dict((baseline or {}).get("metrics") or {})
    if not baseline_metrics:
        return {"status": "no_baseline", "deltas": {}, "passed": False}

    deltas = {
        "total_return": round(float(candidate_metrics.get("total_return") or 0) - float(baseline_metrics.get("total_return") or 0), 6),
        "max_drawdown": round(float(candidate_metrics.get("max_drawdown") or 0) - float(baseline_metrics.get("max_drawdown") or 0), 6),
        "trade_count": int(candidate_metrics.get("trade_count") or 0) - int(baseline_metrics.get("trade_count") or 0),
    }
    passed = deltas["total_return"] > 0 and float(candidate_metrics.get("max_drawdown") or 0) >= float(baseline_metrics.get("max_drawdown") or 0) - 0.03
    return {"status": "compared", "deltas": deltas, "passed": passed}


def build_experiment_record(
    name: str,
    candidate: ParameterSearchResult | dict[str, Any],
    baseline: ParameterSearchResult | dict[str, Any] | None = None,
    experiment_id: str | None = None,
) -> ExperimentRecord:
    candidate_payload = search_result_payload(candidate) if isinstance(candidate, ParameterSearchResult) else dict(candidate)
    baseline_payload = None
    if baseline is not None:
        baseline_payload = search_result_payload(baseline) if isinstance(baseline, ParameterSearchResult) else dict(baseline)
    comparison = compare_candidate_to_baseline(candidate_payload, baseline_payload)
    if comparison["status"] == "no_baseline":
        status = "candidate"
        decision = "missing_baseline"
    elif comparison["passed"]:
        status = "passed"
        decision = "candidate_improved_baseline"
    else:
        status = "rejected"
        decision = "candidate_did_not_clear_baseline"
    return ExperimentRecord(
        experiment_id=experiment_id or str(uuid4()),
        name=name,
        status=status,
        candidate={**candidate_payload, "comparison": comparison},
        baseline=baseline_payload,
        decision=decision,
        created_at=datetime.now(UTC).isoformat(),
    )


def experiment_record_payload(record: ExperimentRecord) -> dict[str, Any]:
    return {
        "experiment_id": record.experiment_id,
        "name": record.name,
        "status": record.status,
        "candidate": record.candidate,
        "baseline": record.baseline,
        "decision": record.decision,
        "created_at": record.created_at,
    }
