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
