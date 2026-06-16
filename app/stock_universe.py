from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    name: str
    market: str
    sector: str
    lot_size: int = 100
    source: str = "manual"


def normalize_a_share_symbol(value: str) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "." in text:
        code, market = text.split(".", 1)
    else:
        code = text
        market = "SH" if code.startswith(("6", "9")) else "SZ"
    if not re.fullmatch(r"\d{6}", code):
        return None
    if market not in {"SH", "SZ"}:
        return None
    return f"{code}.{market}"


def is_tradeable_a_share_name(name: str) -> bool:
    normalized = str(name or "").strip().upper()
    if not normalized:
        return False
    return "退市" not in normalized and not normalized.startswith(("ST", "*ST"))


def stock_candidate_from_row(row: dict, default_source: str = "manual") -> StockCandidate | None:
    symbol = normalize_a_share_symbol(str(row.get("symbol") or row.get("code") or ""))
    name = str(row.get("name") or row.get("股票名称") or "").strip()
    if not symbol or not is_tradeable_a_share_name(name):
        return None
    market = symbol.split(".")[-1]
    sector = str(row.get("sector") or row.get("industry") or row.get("行业") or "未分类").strip() or "未分类"
    lot_size = int(row.get("lot_size") or 100)
    source = str(row.get("source") or default_source)
    return StockCandidate(symbol=symbol, name=name, market=market, sector=sector, lot_size=lot_size, source=source)


def build_public_universe(rows: Iterable[dict], limit: int = 500, default_source: str = "manual") -> list[StockCandidate]:
    out: list[StockCandidate] = []
    seen: set[str] = set()
    for row in rows:
        candidate = stock_candidate_from_row(row, default_source=default_source)
        if not candidate or candidate.symbol in seen:
            continue
        out.append(candidate)
        seen.add(candidate.symbol)
        if len(out) >= limit:
            break
    return out


def universe_summary(candidates: Iterable[StockCandidate]) -> dict[str, object]:
    rows = list(candidates)
    by_market: dict[str, int] = {}
    by_sector: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in rows:
        by_market[row.market] = by_market.get(row.market, 0) + 1
        by_sector[row.sector] = by_sector.get(row.sector, 0) + 1
        by_source[row.source] = by_source.get(row.source, 0) + 1
    return {
        "count": len(rows),
        "by_market": dict(sorted(by_market.items())),
        "by_sector": dict(sorted(by_sector.items())),
        "by_source": dict(sorted(by_source.items())),
        "sample": [row.symbol for row in rows[:10]],
    }
