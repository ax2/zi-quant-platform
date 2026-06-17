from datetime import date, datetime

from app.run_request import build_daily_run_request, request_symbol_count


def test_build_daily_run_request_deduplicates_and_strips_symbols():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 3),
        generated_at=datetime(2026, 2, 3, 15, 20),
        required_symbols=["000001.SZ", " 600000.SH ", "000001.SZ", ""],
        dry_run=False,
    )

    assert request.trade_date == date(2026, 2, 3)
    assert request.required_symbols == ("000001.SZ", "600000.SH")
    assert request.dry_run is False
    assert request_symbol_count(request) == 2


def test_build_daily_run_request_defaults_to_dry_run():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 3),
        generated_at=datetime(2026, 2, 3, 15, 20),
        required_symbols=[],
    )

    assert request.dry_run is True
    assert request.required_symbols == ()
