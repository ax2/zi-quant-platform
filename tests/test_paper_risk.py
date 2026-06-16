from datetime import date

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_risk import evaluate_paper_risk
from app.paper_snapshots import build_paper_account_snapshot


def _snapshot(cash: float = 10000.0):
    account = PaperAccountState(
        cash=cash,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 3000, 10.0)},
    )
    return build_paper_account_snapshot(
        account,
        trade_date=date(2026, 1, 9),
        last_prices={"000001.SZ": 10.0},
    )


def test_risk_passes_when_limits_are_satisfied():
    report = evaluate_paper_risk(_snapshot(cash=70000.0), max_position_weight=0.35, min_cash_ratio=0.1)

    assert report.passed is True
    assert report.severity == "ok"
    assert report.violations == ()


def test_risk_flags_large_position_and_low_cash():
    report = evaluate_paper_risk(_snapshot(cash=1000.0), max_position_weight=0.4, min_cash_ratio=0.1, max_exposure_ratio=1.0)

    assert report.passed is False
    assert report.severity == "blocker"
    codes = {item.code for item in report.violations}
    assert codes == {"position_too_large", "cash_too_low"}
    assert any(item.symbol == "000001.SZ" for item in report.violations)


def test_risk_flags_total_exposure():
    report = evaluate_paper_risk(_snapshot(cash=1000.0), max_position_weight=1.0, min_cash_ratio=0.0, max_exposure_ratio=0.8)

    assert report.severity == "blocker"
    assert [item.code for item in report.violations] == ["exposure_too_high"]
