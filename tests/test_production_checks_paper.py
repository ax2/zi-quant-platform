from datetime import date

from app.paper_daily_cycle import run_paper_daily_cycle
from app.paper_ledger import PaperAccountState, PaperPositionState
from app.production_checks import check_paper_cycle_inputs, check_paper_cycle_result


def test_input_checks_pass_for_valid_cycle_inputs():
    account = PaperAccountState(
        cash=10000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )

    report = check_paper_cycle_inputs(
        account,
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
        target_weights={"000001.SZ": 0.2, "600000.SH": 0.3},
    )

    assert report.passed is True
    assert report.issues == ()


def test_input_checks_report_blockers():
    account = PaperAccountState(
        cash=-1.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )

    report = check_paper_cycle_inputs(
        account,
        last_prices={"600000.SH": 0.0},
        target_weights={"000001.SZ": 0.8, "600000.SH": 0.4, "300001.SZ": -0.1},
    )

    codes = {issue.code for issue in report.issues}
    assert report.passed is False
    assert codes == {"negative_cash", "missing_prices", "invalid_prices", "target_weight_too_high", "negative_target_weight"}


def test_result_checks_pass_for_valid_daily_cycle():
    account = PaperAccountState(cash=10000.0)
    result = run_paper_daily_cycle(
        account,
        trade_date=date(2026, 1, 20),
        last_prices={},
        target_weights={},
    )

    report = check_paper_cycle_result(result)

    assert report.passed is True
