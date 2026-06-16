from datetime import date

from app.data_gaps import build_price_gap_plan, gap_symbols
from app.price_providers import PriceSnapshot


def test_build_price_gap_plan_marks_missing_required_prices():
    plan = build_price_gap_plan(
        PriceSnapshot(date(2026, 1, 30), {"000001.SZ": 10.0}, ("600000.SH",)),
        required_symbols=["000001.SZ", "600000.SH", "300001.SZ"],
    )

    assert plan.severity == "blocker"
    assert gap_symbols(plan) == ["300001.SZ", "600000.SH"]
    assert plan.gaps[0].field == "last_price"


def test_build_price_gap_plan_passes_when_all_prices_exist():
    plan = build_price_gap_plan(
        PriceSnapshot(date(2026, 1, 30), {"000001.SZ": 10.0}, ()),
        required_symbols=["000001.SZ"],
    )

    assert plan.severity == "ok"
    assert plan.gaps == ()
