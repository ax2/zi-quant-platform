from scripts.chapter_examples import build_parser, sample_bars


def test_sample_bars_cover_two_symbols():
    bars = sample_bars()

    assert {bar.symbol for bar in bars} == {"000001.SZ", "600519.SH"}
    assert len(bars) > 70
    assert all(bar.source == "sample" for bar in bars)


def test_factor_backtest_parser_defaults_to_reproducible_sample_data():
    parser = build_parser()
    args = parser.parse_args(["factor-backtest"])

    assert args.source == "sample"
    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.short_window == 5
    assert args.long_window == 20


def test_strategy_promotion_parser_defaults_to_reproducible_sample_data():
    parser = build_parser()
    args = parser.parse_args(["strategy-promotion"])

    assert args.source == "sample"
    assert args.symbols == ["000001.SZ", "600519.SH"]
    assert args.short_windows == [3, 5, 8]
    assert args.long_windows == [15, 20, 30]
    assert args.position_ratios == [0.5, 0.8]
    assert args.baseline_short_window == 5


def test_paper_flow_parser_defaults_to_reproducible_sample_account():
    parser = build_parser()
    args = parser.parse_args(["paper-flow"])

    assert args.trade_date == "2026-03-02"
    assert args.initial_cash == 100000.0
    assert args.symbol == "000001.SZ"
    assert args.buy_shares == 6400
    assert args.target_weight == 0.45


def test_paper_ops_parser_defaults_to_reproducible_sample_cycle():
    parser = build_parser()
    args = parser.parse_args(["paper-ops"])

    assert args.trade_date == "2026-03-03"
    assert args.initial_cash == 300000.0
    assert args.primary_symbol == "000001.SZ"
    assert args.secondary_symbol == "600519.SH"
    assert args.secondary_target_weight == 0.35
