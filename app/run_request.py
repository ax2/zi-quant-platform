from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DailyRunRequest:
    trade_date: date
    generated_at: datetime
    required_symbols: tuple[str, ...]
    dry_run: bool = True


def build_daily_run_request(
    *,
    trade_date: date,
    generated_at: datetime,
    required_symbols: list[str],
    dry_run: bool = True,
) -> DailyRunRequest:
    symbols = tuple(symbol.strip() for symbol in dict.fromkeys(required_symbols) if symbol.strip())
    return DailyRunRequest(
        trade_date=trade_date,
        generated_at=generated_at,
        required_symbols=symbols,
        dry_run=dry_run,
    )


def request_symbol_count(request: DailyRunRequest) -> int:
    return len(request.required_symbols)
