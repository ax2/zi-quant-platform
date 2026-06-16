from datetime import date

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_snapshots import build_paper_account_snapshot


def test_build_snapshot_calculates_equity_and_weights():
    account = PaperAccountState(
        cash=20000.0,
        positions={
            "000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0),
            "600000.SH": PaperPositionState("600000.SH", 500, 8.0),
        },
    )

    snapshot = build_paper_account_snapshot(
        account,
        trade_date=date(2026, 1, 9),
        last_prices={"000001.SZ": 11.0, "600000.SH": 7.5},
    )

    assert snapshot.total_equity == 34750.0
    assert snapshot.market_value == 14750.0
    assert snapshot.cash_ratio == 0.57554
    assert [row.symbol for row in snapshot.positions] == ["000001.SZ", "600000.SH"]
    assert snapshot.positions[0].unrealized_pnl == 1000.0
    assert snapshot.positions[0].weight == 0.316547


def test_snapshot_treats_missing_price_as_zero():
    account = PaperAccountState(cash=1000.0, positions={"000001.SZ": PaperPositionState("000001.SZ", 100, 10.0)})

    snapshot = build_paper_account_snapshot(account, trade_date=date(2026, 1, 9), last_prices={})

    assert snapshot.total_equity == 1000.0
    assert snapshot.positions[0].market_value == 0.0
    assert snapshot.positions[0].unrealized_pnl == -1000.0
