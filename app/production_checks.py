from __future__ import annotations

from dataclasses import dataclass

from app.paper_daily_cycle import PaperDailyCycleResult
from app.paper_ledger import PaperAccountState


@dataclass(frozen=True)
class ProductionCheckIssue:
    code: str
    message: str
    severity: str


@dataclass(frozen=True)
class ProductionCheckReport:
    passed: bool
    issues: tuple[ProductionCheckIssue, ...]


def check_paper_cycle_inputs(
    account: PaperAccountState,
    *,
    last_prices: dict[str, float],
    target_weights: dict[str, float],
) -> ProductionCheckReport:
    issues: list[ProductionCheckIssue] = []
    if account.cash < 0:
        issues.append(ProductionCheckIssue("negative_cash", "模拟盘现金不能为负", "blocker"))

    missing_prices = sorted((set(account.positions) | set(target_weights)) - set(last_prices))
    if missing_prices:
        issues.append(ProductionCheckIssue("missing_prices", f"缺少行情价格：{', '.join(missing_prices)}", "blocker"))

    invalid_prices = sorted(symbol for symbol, price in last_prices.items() if float(price) <= 0)
    if invalid_prices:
        issues.append(ProductionCheckIssue("invalid_prices", f"行情价格必须大于 0：{', '.join(invalid_prices)}", "blocker"))

    total_weight = round(sum(float(value) for value in target_weights.values()), 6)
    if total_weight > 1.0:
        issues.append(ProductionCheckIssue("target_weight_too_high", "目标权重合计不能超过 100%", "blocker"))
    if any(float(value) < 0 for value in target_weights.values()):
        issues.append(ProductionCheckIssue("negative_target_weight", "目标权重不能为负", "blocker"))

    return ProductionCheckReport(passed=not issues, issues=tuple(issues))


def check_paper_cycle_result(result: PaperDailyCycleResult) -> ProductionCheckReport:
    issues: list[ProductionCheckIssue] = []
    if result.snapshot.total_equity <= 0:
        issues.append(ProductionCheckIssue("non_positive_equity", "模拟盘总权益必须大于 0", "blocker"))
    if not result.alert_message.body.strip():
        issues.append(ProductionCheckIssue("empty_alert_body", "模拟盘日报正文不能为空", "blocker"))
    if result.review_record.total_equity != result.snapshot.total_equity:
        issues.append(ProductionCheckIssue("review_snapshot_mismatch", "复盘记录总权益必须与快照一致", "blocker"))
    return ProductionCheckReport(passed=not issues, issues=tuple(issues))
