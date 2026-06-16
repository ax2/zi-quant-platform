from datetime import date, timedelta

from app.market_data import CleanMarketBar
from app.parameter_search import parameter_grid, run_parameter_search, score_search_result, search_result_payload


def _bars(symbol: str, closes: list[float]) -> list[CleanMarketBar]:
    start = date(2026, 1, 1)
    return [
        CleanMarketBar(symbol, start + timedelta(days=index), close, close, close, close, 100000, close * 100000, "fixture")
        for index, close in enumerate(closes)
    ]


def test_parameter_grid_filters_invalid_combinations():
    grid = parameter_grid([1, 3, 5], [3, 10], [0, 0.5, 1.2])
    assert [(item.short_window, item.long_window, item.position_ratio) for item in grid] == [(3, 10, 0.5), (5, 10, 0.5)]


def test_run_parameter_search_returns_ranked_payloads():
    closes = [10 + index * 0.12 for index in range(60)]
    results = run_parameter_search(
        "600519.SH",
        _bars("600519.SH", closes),
        short_windows=[3, 5],
        long_windows=[12, 20],
        position_ratios=[0.5, 0.8],
        top_n=3,
    )
    assert len(results) == 3
    scores = [score_search_result(result) for result in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].metrics.trade_count >= 1
    payload = search_result_payload(results[0])
    assert payload["symbol"] == "600519.SH"
    assert "total_return" in payload["metrics"]


def test_run_parameter_search_handles_empty_data():
    results = run_parameter_search("600519.SH", [], short_windows=[3], long_windows=[12], position_ratios=[0.5])
    assert len(results) == 1
    assert results[0].final_equity == 100000
    assert score_search_result(results[0]) < 0
