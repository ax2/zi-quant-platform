from app.trading_rules import check_a_share_order, estimate_a_share_fee, normalize_a_share_lot


def test_normalize_a_share_lot_rounds_down_to_board_lot():
    assert normalize_a_share_lot(99) == 0
    assert normalize_a_share_lot(100) == 100
    assert normalize_a_share_lot(258) == 200
    assert normalize_a_share_lot(-100) == 0


def test_estimate_a_share_fee_breaks_down_buy_and_sell_costs():
    buy = estimate_a_share_fee(20_000, "buy")
    sell = estimate_a_share_fee(20_000, "sell")

    assert buy.commission == 6.0
    assert buy.transfer_fee == 0.2
    assert buy.stamp_tax == 0.0
    assert buy.total == 6.2
    assert sell.total == 16.2


def test_check_a_share_order_validates_lot_cash_and_position():
    accepted = check_a_share_order(side="buy", price=10.0, shares=258, available_cash=2500)
    assert accepted.accepted is True
    assert accepted.normalized_shares == 200
    assert accepted.amount == 2000

    low_cash = check_a_share_order(side="buy", price=10.0, shares=300, available_cash=1000)
    assert low_cash.accepted is False
    assert low_cash.reason == "insufficient_cash"

    low_position = check_a_share_order(side="sell", price=10.0, shares=300, available_shares=200)
    assert low_position.accepted is False
    assert low_position.reason == "insufficient_position"
