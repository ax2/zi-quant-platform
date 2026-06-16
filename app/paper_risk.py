from __future__ import annotations

from dataclasses import dataclass

from app.paper_snapshots import PaperAccountSnapshot


@dataclass(frozen=True)
class PaperRiskViolation:
    code: str
    message: str
    value: float
    limit: float
    severity: str
    symbol: str | None = None


@dataclass(frozen=True)
class PaperRiskReport:
    passed: bool
    severity: str
    violations: tuple[PaperRiskViolation, ...]


def evaluate_paper_risk(
    snapshot: PaperAccountSnapshot,
    *,
    max_position_weight: float = 0.35,
    min_cash_ratio: float = 0.05,
    max_exposure_ratio: float = 0.95,
) -> PaperRiskReport:
    violations: list[PaperRiskViolation] = []

    exposure_ratio = round(snapshot.market_value / snapshot.total_equity, 6) if snapshot.total_equity else 0.0
    if exposure_ratio > max_exposure_ratio:
        violations.append(
            PaperRiskViolation(
                code="exposure_too_high",
                message="总仓位超过模拟盘上限",
                value=exposure_ratio,
                limit=max_exposure_ratio,
                severity="blocker",
            )
        )

    if snapshot.cash_ratio < min_cash_ratio:
        violations.append(
            PaperRiskViolation(
                code="cash_too_low",
                message="现金缓冲低于模拟盘要求",
                value=snapshot.cash_ratio,
                limit=min_cash_ratio,
                severity="warning",
            )
        )

    for position in snapshot.positions:
        if position.weight > max_position_weight:
            violations.append(
                PaperRiskViolation(
                    code="position_too_large",
                    message="单只股票持仓权重过高",
                    value=position.weight,
                    limit=max_position_weight,
                    severity="blocker",
                    symbol=position.symbol,
                )
            )

    severity = "ok"
    if any(item.severity == "blocker" for item in violations):
        severity = "blocker"
    elif violations:
        severity = "warning"
    return PaperRiskReport(passed=not violations, severity=severity, violations=tuple(violations))
