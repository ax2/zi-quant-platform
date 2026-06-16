from app.experiment_records import build_experiment_record, compare_candidate_to_baseline, experiment_record_payload


def _payload(total_return: float, max_drawdown: float = -0.05, trade_count: int = 2) -> dict:
    return {
        "symbol": "600519.SH",
        "params": {"short_window": 5, "long_window": 20, "position_ratio": 0.8},
        "final_equity": 100000 * (1 + total_return),
        "score": total_return,
        "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "trade_count": trade_count},
    }


def test_compare_candidate_to_baseline_detects_missing_baseline():
    comparison = compare_candidate_to_baseline(_payload(0.1), None)
    assert comparison == {"status": "no_baseline", "deltas": {}, "passed": False}


def test_compare_candidate_to_baseline_marks_passed_candidate():
    comparison = compare_candidate_to_baseline(_payload(0.12, -0.05), _payload(0.08, -0.04))
    assert comparison["status"] == "compared"
    assert comparison["deltas"]["total_return"] == 0.04
    assert comparison["passed"] is True


def test_build_experiment_record_rejects_weak_candidate():
    record = build_experiment_record("弱候选", _payload(0.05, -0.12), _payload(0.08, -0.04), experiment_id="exp-1")
    assert record.experiment_id == "exp-1"
    assert record.status == "rejected"
    assert record.decision == "candidate_did_not_clear_baseline"
    payload = experiment_record_payload(record)
    assert payload["candidate"]["comparison"]["passed"] is False


def test_build_experiment_record_without_baseline_stays_candidate():
    record = build_experiment_record("待比较候选", _payload(0.1), experiment_id="exp-2")
    assert record.status == "candidate"
    assert record.decision == "missing_baseline"
    assert record.baseline is None
