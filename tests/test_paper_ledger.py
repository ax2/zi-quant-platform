from datetime import date

from app.paper_ledger import PaperAccountState, account_market_value, account_total_equity, apply_paper_order


def test_apply_paper_buy_updates_cash_position_and_average_cost():
    account = PaperAccountState(cash=100000)
    execution = apply_paper_order(account, trade_date=date(2026, 1, 2), symbol="600519.SH", side="buy", price=10, shares=1234)
    assert execution.accepted is True
    assert execution.filled_shares == 1200
    assert execution.account.cash == 87994.88
    position = execution.account.positions["600519.SH"]
    assert position.shares == 1200
    assert position.avg_cost == 10.004267


def test_apply_paper_buy_rejects_insufficient_cash_without_mutating_account():
    account = PaperAccountState(cash=1000)
    execution = apply_paper_order(account, trade_date=date(2026, 1, 2), symbol="600519.SH", side="buy", price=10, shares=1000)
    assert execution.accepted is False
    assert execution.reason == "insufficient_cash"
    assert execution.account is account


def test_apply_paper_sell_realizes_pnl_and_removes_closed_position():
    account = apply_paper_order(PaperAccountState(cash=100000), trade_date=date(2026, 1, 2), symbol="600519.SH", side="buy", price=10, shares=1000).account
    execution = apply_paper_order(account, trade_date=date(2026, 1, 5), symbol="600519.SH", side="sell", price=12, shares=1000)
    assert execution.accepted is True
    assert execution.filled_shares == 1000
    assert "600519.SH" not in execution.account.positions
    assert execution.account.cash > 101900


def test_apply_paper_sell_rejects_missing_position():
    account = PaperAccountState(cash=100000)
    execution = apply_paper_order(account, trade_date=date(2026, 1, 5), symbol="600519.SH", side="sell", price=12, shares=100)
    assert execution.accepted is False
    assert execution.reason == "insufficient_position"


def test_account_market_value_and_total_equity_use_last_prices():
    account = apply_paper_order(PaperAccountState(cash=100000), trade_date=date(2026, 1, 2), symbol="600519.SH", side="buy", price=10, shares=1000).account
    assert account_market_value(account, {"600519.SH": 12}) == 12000
    assert account_total_equity(account, {"600519.SH": 12}) == round(account.cash + 12000, 2)
