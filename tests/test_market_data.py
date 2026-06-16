from datetime import date

from app.market_data import clean_market_bars, coverage_report, parse_number, parse_trade_date


def test_parse_helpers_accept_common_vendor_formats():
    assert parse_trade_date("20260616") == date(2026, 6, 16)
    assert parse_trade_date("2026/06/16") == date(2026, 6, 16)
    assert parse_trade_date("-") is None
    assert parse_number("1,234.50") == 1234.5
    assert parse_number("--") is None


def test_clean_market_bars_normalizes_units_and_amount():
    rows = [
        {"日期": "2026-06-15", "开盘": "10.0", "最高": "10.8", "最低": "9.9", "收盘": "10.5", "成交量": "120", "成交额": ""},
        {"日期": "2026-06-16", "开盘": "10.5", "最高": "10.9", "最低": "10.2", "收盘": "10.8", "成交量": "150", "成交额": "162000"},
    ]
    bars, rejected = clean_market_bars("600519.SH", rows, source="eastmoney", volume_unit="lot")
    assert rejected == []
    assert [bar.trade_date for bar in bars] == [date(2026, 6, 15), date(2026, 6, 16)]
    assert bars[0].volume == 12000
    assert bars[0].amount == 126000
    assert bars[1].amount == 162000
    assert bars[0].payload["volume_unit"] == "shares"


def test_clean_market_bars_rejects_bad_rows_and_duplicates():
    rows = [
        {"date": "2026-06-15", "open": 10, "high": 9, "low": 8, "close": 10},
        {"date": "2026-06-16", "close": 10},
        {"date": "2026-06-16", "close": 11},
        {"date": "", "close": 11},
        {"date": "2026-06-17", "close": 0},
    ]
    bars, rejected = clean_market_bars("000001.SZ", rows, source="fixture")
    assert len(bars) == 1
    assert [item["reason"] for item in rejected] == ["invalid_ohlc_range", "duplicate_trade_date", "missing_trade_date", "invalid_close"]


def test_coverage_report_summarizes_clean_bars():
    bars, _ = clean_market_bars(
        "300750.SZ",
        [{"date": "2026-06-15", "close": 100}, {"date": "2026-06-16", "close": 101}],
        source="fixture",
    )
    report = coverage_report(bars)
    assert report == {
        "rows": 2,
        "symbols": 1,
        "first_date": "2026-06-15",
        "latest_date": "2026-06-16",
        "sources": ["fixture"],
    }
