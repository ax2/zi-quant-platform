from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetWeightPolicy:
    max_symbols: int = 5
    gross_exposure: float = 0.8
    min_weight: float = 0.01


def build_equal_weight_targets(candidates: list[str], policy: TargetWeightPolicy | None = None) -> dict[str, float]:
    rule = policy or TargetWeightPolicy()
    if rule.max_symbols <= 0 or rule.gross_exposure <= 0:
        return {}

    selected = list(dict.fromkeys(symbol for symbol in candidates if symbol))
    selected = selected[: rule.max_symbols]
    if not selected:
        return {}

    raw_weight = round(min(rule.gross_exposure, 1.0) / len(selected), 6)
    if raw_weight < rule.min_weight:
        return {}
    return {symbol: raw_weight for symbol in selected}


def normalize_target_weights(targets: dict[str, float], *, max_total: float = 1.0) -> dict[str, float]:
    cleaned = {symbol: float(weight) for symbol, weight in targets.items() if symbol and float(weight) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    scale = min(max_total, total) / total
    return {symbol: round(weight * scale, 6) for symbol, weight in sorted(cleaned.items())}
