from app.schema_checks import CORE_TABLES, migration_readiness, schema_readiness, summarize_metadata


def test_summarize_metadata_includes_core_relationships():
    summaries = {summary.name: summary for summary in summarize_metadata()}
    assert "zi_quant_market_bars" in summaries
    assert summaries["zi_quant_market_bars"].primary_key == ("id",)
    assert "symbol->zi_quant_stocks.symbol" in summaries["zi_quant_market_bars"].foreign_keys
    assert "uq_zi_quant_bar_symbol_date_freq" in summaries["zi_quant_market_bars"].unique_constraints


def test_schema_readiness_checks_required_tables_and_primary_keys():
    ready = schema_readiness()
    assert ready["status"] == "ready"
    assert ready["missing_tables"] == []
    assert ready["tables_without_primary_key"] == []
    assert ready["required_table_count"] == len(CORE_TABLES)

    degraded = schema_readiness(required_tables={*CORE_TABLES, "zi_quant_missing_table"})
    assert degraded["status"] == "degraded"
    assert degraded["missing_tables"] == ["zi_quant_missing_table"]


def test_migration_readiness_finds_alembic_versions():
    readiness = migration_readiness()
    assert readiness["status"] == "ready"
    assert readiness["revision_count"] >= 5
    assert str(readiness["latest_revision_file"]).endswith(".py")
