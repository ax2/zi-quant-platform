from app.stock_universe import build_public_universe, is_tradeable_a_share_name, normalize_a_share_symbol, stock_candidate_from_row, universe_summary


def test_normalize_a_share_symbol_infers_market_and_rejects_bad_values():
    assert normalize_a_share_symbol("600519") == "600519.SH"
    assert normalize_a_share_symbol("000001") == "000001.SZ"
    assert normalize_a_share_symbol("300750.sz") == "300750.SZ"
    assert normalize_a_share_symbol("abc") is None
    assert normalize_a_share_symbol("600519.BJ") is None


def test_tradeable_name_filter_rejects_st_and_delisted_rows():
    assert is_tradeable_a_share_name("贵州茅台") is True
    assert is_tradeable_a_share_name("ST某公司") is False
    assert is_tradeable_a_share_name("*ST某公司") is False
    assert is_tradeable_a_share_name("退市整理") is False


def test_stock_candidate_from_row_normalizes_common_fields():
    candidate = stock_candidate_from_row({"code": "600036", "股票名称": "招商银行", "行业": "银行", "source": "eastmoney"})
    assert candidate is not None
    assert candidate.symbol == "600036.SH"
    assert candidate.market == "SH"
    assert candidate.sector == "银行"
    assert candidate.source == "eastmoney"


def test_build_public_universe_deduplicates_filters_and_limits():
    rows = [
        {"symbol": "600519.SH", "name": "贵州茅台", "sector": "白酒"},
        {"symbol": "600519.SH", "name": "贵州茅台", "sector": "白酒"},
        {"symbol": "000001", "name": "平安银行", "sector": "银行"},
        {"symbol": "000002", "name": "ST测试", "sector": "地产"},
        {"symbol": "300750", "name": "宁德时代", "sector": "新能源"},
    ]
    universe = build_public_universe(rows, limit=2, default_source="fixture")
    assert [row.symbol for row in universe] == ["600519.SH", "000001.SZ"]
    assert all(row.source == "fixture" for row in universe)


def test_universe_summary_groups_markets_sectors_and_sources():
    universe = build_public_universe(
        [
            {"symbol": "600519.SH", "name": "贵州茅台", "sector": "白酒", "source": "eastmoney"},
            {"symbol": "000001.SZ", "name": "平安银行", "sector": "银行", "source": "eastmoney"},
            {"symbol": "300750.SZ", "name": "宁德时代", "sector": "新能源", "source": "qveris"},
        ]
    )
    summary = universe_summary(universe)
    assert summary["count"] == 3
    assert summary["by_market"] == {"SH": 1, "SZ": 2}
    assert summary["by_source"] == {"eastmoney": 2, "qveris": 1}
    assert summary["sample"] == ["600519.SH", "000001.SZ", "300750.SZ"]
