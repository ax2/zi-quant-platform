from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class CleanMarketBar:
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    source: str
    payload: dict[str, Any] = field(default_factory=dict)


def parse_trade_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "--", "nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row:
            return row[key]
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def clean_market_bars(symbol: str, rows: Iterable[dict[str, Any]], source: str, volume_unit: str = "shares") -> tuple[list[CleanMarketBar], list[dict[str, Any]]]:
    cleaned: list[CleanMarketBar] = []
    rejected: list[dict[str, Any]] = []
    seen_dates: set[date] = set()
    volume_multiplier = 100 if volume_unit == "lot" else 1

    for row in rows:
        trade_date = parse_trade_date(_pick(row, "trade_date", "date", "日期"))
        open_price = parse_number(_pick(row, "open", "开盘", "开盘价"))
        high = parse_number(_pick(row, "high", "最高", "最高价"))
        low = parse_number(_pick(row, "low", "最低", "最低价"))
        close = parse_number(_pick(row, "close", "收盘", "收盘价"))
        volume = parse_number(_pick(row, "volume", "成交量")) or 0.0
        amount = parse_number(_pick(row, "amount", "成交额"))

        reason = None
        if not trade_date:
            reason = "missing_trade_date"
        elif trade_date in seen_dates:
            reason = "duplicate_trade_date"
        elif close is None or close <= 0:
            reason = "invalid_close"
        else:
            open_price = open_price if open_price and open_price > 0 else close
            high = high if high and high > 0 else max(open_price, close)
            low = low if low and low > 0 else min(open_price, close)
            if high < max(open_price, low, close) or low > min(open_price, high, close):
                reason = "invalid_ohlc_range"

        if reason:
            rejected.append({"reason": reason, "row": row})
            continue

        assert trade_date is not None
        assert open_price is not None and high is not None and low is not None and close is not None
        normalized_volume = round(volume * volume_multiplier, 4)
        normalized_amount = amount if amount is not None else round(normalized_volume * close, 2)
        cleaned.append(
            CleanMarketBar(
                symbol=symbol,
                trade_date=trade_date,
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=normalized_volume,
                amount=round(normalized_amount, 2),
                source=source,
                payload={"raw": row, "volume_unit": "shares"},
            )
        )
        seen_dates.add(trade_date)

    return sorted(cleaned, key=lambda item: item.trade_date), rejected


def coverage_report(bars: Iterable[CleanMarketBar]) -> dict[str, object]:
    rows = list(bars)
    dates = [row.trade_date for row in rows]
    symbols = sorted({row.symbol for row in rows})
    return {
        "rows": len(rows),
        "symbols": len(symbols),
        "first_date": min(dates).isoformat() if dates else None,
        "latest_date": max(dates).isoformat() if dates else None,
        "sources": sorted({row.source for row in rows}),
    }
