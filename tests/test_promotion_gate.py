from app.promotion_gate import PromotionRule, evaluate_strategy_promotion, promotion_decision_payload, promotion_summary


def _record(total_return=0.08, max_drawdown=-0.06, trade_count=3, baseline_passed=True):
    return {
        "candidate": {
            "metrics": {"total_return": total_return, "max_drawdown": max_drawdown, "trade_count": trade_count},
            "comparison": {"passed": baseline_passed},
        }
    }


def test_evaluate_strategy_promotion_accepts_candidate_with_evidence():
    decision = evaluate_strategy_promotion(_record())
    assert decision.accepted is True
    assert decision.status == "accepted_for_paper_observation"
    assert decision.reasons == ()
    payload = promotion_decision_payload(decision)
    assert payload["evidence"]["baseline_passed"] is True


def test_evaluate_strategy_promotion_collects_all_rejection_reasons():
    decision = evaluate_strategy_promotion(_record(total_return=-0.01, max_drawdown=-0.35, trade_count=0, baseline_passed=False))
    assert decision.accepted is False
    assert set(decision.reasons) == {
        "total_return_below_minimum",
        "max_drawdown_too_deep",
        "trade_count_too_low",
        "baseline_not_cleared",
    }


def test_evaluate_strategy_promotion_can_disable_baseline_requirement():
    decision = evaluate_strategy_promotion(_record(baseline_passed=False), PromotionRule(require_baseline_passed=False))
    assert decision.accepted is True


def test_promotion_summary_counts_accepted_and_rejection_reasons():
    summary = promotion_summary([_record(), _record(total_return=0.0, baseline_passed=False)])
    assert summary["candidate_count"] == 2
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["reason_counts"]["total_return_below_minimum"] == 1
    assert summary["reason_counts"]["baseline_not_cleared"] == 1
