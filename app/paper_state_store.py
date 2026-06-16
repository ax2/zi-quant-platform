from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paper_ledger import PaperAccountState, PaperPositionState


def paper_account_to_dict(account: PaperAccountState) -> dict[str, Any]:
    return {
        "cash": account.cash,
        "positions": {
            symbol: {
                "symbol": position.symbol,
                "shares": position.shares,
                "avg_cost": position.avg_cost,
                "realized_pnl": position.realized_pnl,
            }
            for symbol, position in sorted(account.positions.items())
        },
    }


def paper_account_from_dict(payload: dict[str, Any]) -> PaperAccountState:
    positions = {
        symbol: PaperPositionState(
            symbol=str(item.get("symbol", symbol)),
            shares=int(item["shares"]),
            avg_cost=float(item["avg_cost"]),
            realized_pnl=float(item.get("realized_pnl", 0.0)),
        )
        for symbol, item in dict(payload.get("positions", {})).items()
    }
    return PaperAccountState(cash=float(payload["cash"]), positions=positions)


def save_paper_account(account: PaperAccountState, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(paper_account_to_dict(account), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_paper_account(path: str | Path) -> PaperAccountState:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return paper_account_from_dict(payload)
