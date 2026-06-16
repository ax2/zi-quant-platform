from datetime import date

from app.price_providers import StaticPriceProvider, collect_required_price_symbols


def test_static_price_provider_returns_found_and_missing_symbols():
    provider = StaticPriceProvider({"000001.SZ": 10.0, "600000.SH": 8.5})

    snapshot = provider.get_last_prices(["000001.SZ", "000001.SZ", "300001.SZ"], trade_date=date(2026, 1, 23))

    assert snapshot.trade_date == date(2026, 1, 23)
    assert snapshot.prices == {"000001.SZ": 10.0}
    assert snapshot.missing_symbols == ("300001.SZ",)


def test_collect_required_price_symbols_merges_positions_and_targets():
    symbols = collect_required_price_symbols(
        ["000001.SZ", "600000.SH"],
        {"600000.SH": 0.2, "300001.SZ": 0.1},
    )

    assert symbols == ["000001.SZ", "300001.SZ", "600000.SH"]
