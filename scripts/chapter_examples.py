from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.alert_messages import format_paper_daily_alert
from app.daily_run_plan import build_daily_run_plan, plan_can_execute
from app.data_gaps import build_price_gap_plan, gap_symbols
from app.experiment_records import build_experiment_record, experiment_record_payload
from app.factors import build_factor_points
from app.file_notifications import FileNotificationChannel, read_file_notifications
from app.market_data import CleanMarketBar, clean_market_bars, coverage_report
from app.mini_backtest import run_signal_backtest
from app.notification_channels import MemoryNotificationChannel, send_paper_alert
from app.parameter_search import run_parameter_search, score_search_result
from app.paper_daily_cycle import run_paper_daily_cycle
from app.paper_ledger import PaperAccountState, apply_paper_order
from app.paper_review import summarize_paper_reviews
from app.paper_risk import evaluate_paper_risk
from app.paper_snapshots import build_paper_account_snapshot
from app.paper_state_store import load_paper_account, save_paper_account
from app.performance_metrics import compute_performance_metrics
from app.portfolio_backtest import portfolio_trade_summary, run_equal_weight_portfolio_backtest
from app.price_providers import StaticPriceProvider, collect_required_price_symbols
from app.production_checks import check_paper_cycle_inputs, check_paper_cycle_result
from app.promotion_gate import evaluate_strategy_promotion, promotion_decision_payload
from app.rebalance_plan import build_rebalance_plan
from app.report_archive import archive_daily_report, read_archived_report
from app.report_index import build_report_index, latest_report_entry
from app.run_health import RunHealthReport, build_run_health_report
from app.run_history import summarize_archived_reports
from app.run_request import build_daily_run_request, request_symbol_count
from app.run_window import RunWindow, evaluate_run_window
from app.ops_checklist import build_ops_checklist
from app.target_weight_policy import TargetWeightPolicy, build_equal_weight_targets, normalize_target_weights


def _sample_rows(*, start: date, days: int, base: float, drift: float, shock_after: int | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    price = base
    for offset in range(days):
        trade_date = start + timedelta(days=offset)
        if trade_date.weekday() >= 5:
            continue
        wave = math.sin(offset / 3) * 0.18
        price = max(1.0, price + drift + wave)
        if shock_after is not None and offset >= shock_after:
            price *= 0.985
        open_price = round(price * 0.995, 2)
        close = round(price, 2)
        high = round(max(open_price, close) * 1.015, 2)
        low = round(min(open_price, close) * 0.985, 2)
        volume = 1_000_000 + offset * 20_000
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": round(volume * close, 2),
            }
        )
    return rows


def sample_bars() -> list[CleanMarketBar]:
    specs = {
        "000001.SZ": {"base": 10.0, "drift": 0.08, "shock_after": None},
        "600519.SH": {"base": 1500.0, "drift": 2.8, "shock_after": 34},
    }
    bars: list[CleanMarketBar] = []
    for symbol, spec in specs.items():
        cleaned, rejected = clean_market_bars(
            symbol,
            _sample_rows(start=date(2026, 1, 2), days=58, **spec),
            source="sample",
        )
        if rejected:
            raise RuntimeError(f"sample data unexpectedly rejected: {rejected[:1]}")
        bars.extend(cleaned)
    return sorted(bars, key=lambda item: (item.symbol, item.trade_date))


def _eastmoney_secid(symbol: str) -> str:
    code, _, suffix = symbol.partition(".")
    if suffix.upper() == "SH":
        return f"1.{code}"
    if suffix.upper() == "SZ":
        return f"0.{code}"
    raise ValueError(f"unsupported symbol suffix: {symbol}")


def eastmoney_bars(symbols: Iterable[str], *, begin: str, end: str) -> list[CleanMarketBar]:
    bars: list[CleanMarketBar] = []
    for symbol in symbols:
        params = {
            "secid": _eastmoney_secid(symbol),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": "101",
            "fqt": "1",
            "beg": begin,
            "end": end,
        }
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 ZiQuantExample/1.0",
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
            },
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        klines = ((payload.get("data") or {}).get("klines") or [])[-80:]
        rows = []
        for line in klines:
            trade_date, open_price, close, high, low, volume, amount = line.split(",")[:7]
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                }
            )
        cleaned, rejected = clean_market_bars(symbol, rows, source="eastmoney")
        if rejected:
            print(f"{symbol} rejected_rows={len(rejected)}")
        bars.extend(cleaned)
    return sorted(bars, key=lambda item: (item.symbol, item.trade_date))


def _load_bars(args: argparse.Namespace) -> list[CleanMarketBar]:
    if args.source == "eastmoney":
        return eastmoney_bars(args.symbols, begin=args.begin, end=args.end)
    return [bar for bar in sample_bars() if bar.symbol in set(args.symbols)]


def print_factor_backtest(args: argparse.Namespace) -> int:
    bars = _load_bars(args)
    print("coverage", coverage_report(bars))

    first_symbol = args.symbols[0]
    first_bars = [bar for bar in bars if bar.symbol == first_symbol]
    factors = build_factor_points(first_bars, short_window=args.short_window, long_window=args.long_window, volatility_window=args.short_window)
    print(f"\nchapter-09 factors {first_symbol}")
    for point in factors[-5:]:
        print(
            point.trade_date.isoformat(),
            f"close={point.close:.2f}",
            f"ma_short={point.ma_short}",
            f"ma_long={point.ma_long}",
            f"momentum={point.momentum}",
            f"volatility={point.volatility}",
            f"signal={point.signal}",
        )

    single = run_signal_backtest(
        first_symbol,
        first_bars,
        initial_cash=args.initial_cash,
        short_window=args.short_window,
        long_window=args.long_window,
    )
    print(f"\nchapter-10 mini_backtest {first_symbol}")
    print(
        f"final_equity={single.final_equity:.2f}",
        f"total_return={single.total_return:.4%}",
        f"max_drawdown={single.max_drawdown:.4%}",
        f"trades={len(single.trades)}",
    )
    for trade in single.trades[:4]:
        print(trade.trade_date.isoformat(), trade.side, f"shares={trade.shares}", f"price={trade.price:.2f}", trade.reason)

    portfolio = run_equal_weight_portfolio_backtest(
        args.symbols,
        bars,
        initial_cash=args.initial_cash,
        position_ratio=0.8,
    )
    print("\nchapter-11 portfolio_backtest")
    print(
        f"symbols={len(portfolio.symbol_results)}",
        f"final_equity={portfolio.final_equity:.2f}",
        f"total_return={portfolio.total_return:.4%}",
        f"max_drawdown={portfolio.max_drawdown:.4%}",
        f"trade_summary={portfolio_trade_summary(portfolio)}",
    )

    all_trades = [trade for result in portfolio.symbol_results for trade in result.trades]
    metrics = compute_performance_metrics(
        portfolio.equity_curve,
        all_trades,
        initial_cash=args.initial_cash,
        max_drawdown=portfolio.max_drawdown,
    )
    print("\nchapter-12 performance_metrics")
    print(metrics)
    return 0


def print_strategy_promotion(args: argparse.Namespace) -> int:
    bars = _load_bars(args)
    print("coverage", coverage_report(bars))

    symbol = args.symbols[0]
    ranked = run_parameter_search(
        symbol,
        bars,
        initial_cash=args.initial_cash,
        short_windows=args.short_windows,
        long_windows=args.long_windows,
        position_ratios=args.position_ratios,
        top_n=args.top_n,
    )
    baseline = run_parameter_search(
        symbol,
        bars,
        initial_cash=args.initial_cash,
        short_windows=(args.baseline_short_window,),
        long_windows=(args.baseline_long_window,),
        position_ratios=(args.baseline_position_ratio,),
        top_n=1,
    )[0]
    candidate = ranked[0]

    print(f"\nchapter-13 parameter_search {symbol}")
    for index, result in enumerate(ranked[:3], start=1):
        print(
            f"rank={index}",
            f"params={result.params.__dict__}",
            f"score={score_search_result(result):.6f}",
            f"return={result.metrics.total_return:.4%}",
            f"drawdown={result.metrics.max_drawdown:.4%}",
            f"trades={result.metrics.trade_count}",
        )

    record = build_experiment_record(
        "sample-momentum-parameter-search",
        candidate=candidate,
        baseline=baseline,
        experiment_id="sample-exp-001",
    )
    record_payload = experiment_record_payload(record)
    comparison = record_payload["candidate"]["comparison"]
    print("\nchapter-14 experiment_record")
    print(
        f"experiment_id={record.experiment_id}",
        f"status={record.status}",
        f"decision={record.decision}",
        f"deltas={comparison['deltas']}",
    )

    decision = evaluate_strategy_promotion(record_payload)
    print("\nchapter-15 promotion_gate")
    print(promotion_decision_payload(decision))
    return 0


def print_paper_flow(args: argparse.Namespace) -> int:
    trade_date = date.fromisoformat(args.trade_date)
    account = PaperAccountState(cash=args.initial_cash)
    print(f"initial_account cash={account.cash:.2f} positions={len(account.positions)}")

    buy = apply_paper_order(
        account,
        trade_date=trade_date,
        symbol=args.symbol,
        side="buy",
        price=args.buy_price,
        shares=args.buy_shares,
    )
    account = buy.account
    print("\nchapter-16 paper_ledger")
    print(
        f"accepted={buy.accepted}",
        f"side={buy.side}",
        f"filled_shares={buy.filled_shares}",
        f"amount={buy.amount:.2f}",
        f"fee={buy.fee:.2f}",
        f"cash_after={account.cash:.2f}",
        f"reason={buy.reason}",
    )

    last_prices = {args.symbol: args.last_price}
    snapshot = build_paper_account_snapshot(account, trade_date=trade_date, last_prices=last_prices)
    print("\nchapter-17 paper_snapshot")
    print(
        f"trade_date={snapshot.trade_date.isoformat()}",
        f"cash={snapshot.cash:.2f}",
        f"market_value={snapshot.market_value:.2f}",
        f"total_equity={snapshot.total_equity:.2f}",
        f"cash_ratio={snapshot.cash_ratio:.2%}",
    )
    for position in snapshot.positions:
        print(
            f"position={position.symbol}",
            f"shares={position.shares}",
            f"avg_cost={position.avg_cost:.4f}",
            f"last_price={position.last_price:.2f}",
            f"weight={position.weight:.2%}",
            f"unrealized_pnl={position.unrealized_pnl:.2f}",
        )

    risk_report = evaluate_paper_risk(
        snapshot,
        max_position_weight=args.max_position_weight,
        min_cash_ratio=args.min_cash_ratio,
        max_exposure_ratio=args.max_exposure_ratio,
    )
    print("\nchapter-18 paper_risk")
    print(f"passed={risk_report.passed} severity={risk_report.severity} violations={len(risk_report.violations)}")
    for violation in risk_report.violations:
        target = f" symbol={violation.symbol}" if violation.symbol else ""
        print(
            f"code={violation.code}{target}",
            f"value={violation.value:.2%}",
            f"limit={violation.limit:.2%}",
            f"severity={violation.severity}",
        )

    target_weights = {args.symbol: args.target_weight}
    plan = build_rebalance_plan(
        account,
        trade_date=trade_date,
        last_prices=last_prices,
        target_weights=target_weights,
        min_trade_value=args.min_trade_value,
    )
    print("\nchapter-19 rebalance_plan")
    print(f"total_equity={plan.total_equity:.2f} orders={len(plan.orders)}")
    for order in plan.orders:
        print(
            f"{order.side} {order.symbol}",
            f"shares={order.shares}",
            f"price={order.price:.2f}",
            f"current_weight={order.current_weight:.2%}",
            f"target_weight={order.target_weight:.2%}",
            f"delta_value={order.delta_value:.2f}",
        )

    alert = format_paper_daily_alert(snapshot, risk_report, plan)
    print("\nchapter-20 alert_message")
    print(f"title={alert.title}")
    print(f"severity={alert.severity}")
    print(alert.body)
    return 0


def print_paper_ops(args: argparse.Namespace) -> int:
    trade_date = date.fromisoformat(args.trade_date)
    previous_date = trade_date - timedelta(days=1)
    account = PaperAccountState(cash=args.initial_cash)

    for symbol, price, shares in (
        (args.primary_symbol, args.primary_buy_price, args.primary_buy_shares),
        (args.secondary_symbol, args.secondary_buy_price, args.secondary_buy_shares),
    ):
        execution = apply_paper_order(
            account,
            trade_date=previous_date,
            symbol=symbol,
            side="buy",
            price=price,
            shares=shares,
        )
        if not execution.accepted:
            raise RuntimeError(f"sample order rejected: {symbol} {execution.reason}")
        account = execution.account

    last_prices = {
        args.primary_symbol: args.primary_last_price,
        args.secondary_symbol: args.secondary_last_price,
    }
    target_weights = {
        args.primary_symbol: args.primary_target_weight,
        args.secondary_symbol: args.secondary_target_weight,
    }

    print("chapter-21-25 paper_ops")
    print(f"seed_account cash={account.cash:.2f} positions={len(account.positions)}")

    input_report = check_paper_cycle_inputs(account, last_prices=last_prices, target_weights=target_weights)
    print("\nchapter-25 input_check")
    print(f"passed={input_report.passed} issues={len(input_report.issues)}")
    for issue in input_report.issues:
        print(f"{issue.severity} {issue.code}: {issue.message}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        state_path = Path(tmp_dir) / "paper-account.json"
        save_paper_account(account, state_path)
        loaded_account = load_paper_account(state_path)
        print("\nchapter-24 state_store")
        print(
            f"saved={state_path.name}",
            f"cash={loaded_account.cash:.2f}",
            f"positions={sorted(loaded_account.positions)}",
        )

        previous_result = run_paper_daily_cycle(
            loaded_account,
            trade_date=previous_date,
            last_prices={
                args.primary_symbol: args.primary_buy_price,
                args.secondary_symbol: args.secondary_buy_price,
            },
            target_weights=target_weights,
            review_note="previous close baseline",
        )
        result = run_paper_daily_cycle(
            loaded_account,
            trade_date=trade_date,
            last_prices=last_prices,
            target_weights=target_weights,
            review_note=args.review_note,
        )

    print("\nchapter-23 daily_cycle")
    print(
        f"trade_date={result.snapshot.trade_date.isoformat()}",
        f"total_equity={result.snapshot.total_equity:.2f}",
        f"risk={result.risk_report.severity}",
        f"orders={len(result.rebalance_plan.orders)}",
        f"alert={result.alert_message.severity}",
    )

    print("\nchapter-21 recommendation")
    print(
        f"action={result.recommendation.action}",
        f"severity={result.recommendation.severity}",
        f"order_count={result.recommendation.order_count}",
    )
    print(f"summary={result.recommendation.summary}")
    print(f"reasons={', '.join(result.recommendation.reasons)}")

    print("\nchapter-22 review_summary")
    summary = summarize_paper_reviews((previous_result.review_record, result.review_record))
    print(
        f"records={len(summary.records)}",
        f"latest_equity={summary.latest_equity:.2f}",
        f"equity_change={summary.equity_change:.2f}",
        f"blocker_days={summary.blocker_days}",
        f"actions={summary.action_counts}",
    )

    print("\nchapter-25 result_check")
    result_report = check_paper_cycle_result(result)
    print(f"passed={result_report.passed} issues={len(result_report.issues)}")
    for issue in result_report.issues:
        print(f"{issue.severity} {issue.code}: {issue.message}")

    return 0


def print_paper_notify(args: argparse.Namespace) -> int:
    trade_date = date.fromisoformat(args.trade_date)
    sent_at = datetime.fromisoformat(args.sent_at).replace(tzinfo=timezone.utc)
    account = PaperAccountState(cash=args.initial_cash)

    seed = apply_paper_order(
        account,
        trade_date=trade_date - timedelta(days=1),
        symbol=args.seed_symbol,
        side="buy",
        price=args.seed_price,
        shares=args.seed_shares,
    )
    if not seed.accepted:
        raise RuntimeError(f"seed order rejected: {seed.reason}")
    account = seed.account

    print("chapter-26-30 paper_notify")
    print(f"seed_account cash={account.cash:.2f} positions={sorted(account.positions)}")

    raw_targets = build_equal_weight_targets(
        args.candidates,
        TargetWeightPolicy(
            max_symbols=args.max_symbols,
            gross_exposure=args.gross_exposure,
            min_weight=args.min_weight,
        ),
    )
    targets = normalize_target_weights(raw_targets, max_total=args.max_total)
    print("\nchapter-29 target_weight_policy")
    print(f"candidates={args.candidates}")
    print(f"raw_targets={raw_targets}")
    print(f"normalized_targets={targets} total={sum(targets.values()):.2%}")

    required_symbols = collect_required_price_symbols(list(account.positions), targets)
    provider = StaticPriceProvider(
        {
            args.seed_symbol: args.seed_last_price,
            args.extra_symbol: args.extra_last_price,
        }
    )
    price_snapshot = provider.get_last_prices(required_symbols, trade_date=trade_date)
    print("\nchapter-28 price_provider")
    print(f"required_symbols={required_symbols}")
    print(f"prices={price_snapshot.prices}")
    print(f"missing_symbols={price_snapshot.missing_symbols}")

    input_report = check_paper_cycle_inputs(account, last_prices=price_snapshot.prices, target_weights=targets)
    if not input_report.passed:
        print("\nchapter-25 input_check")
        print(f"passed={input_report.passed} issues={len(input_report.issues)}")
        for issue in input_report.issues:
            print(f"{issue.severity} {issue.code}: {issue.message}")
        return 1

    result = run_paper_daily_cycle(
        account,
        trade_date=trade_date,
        last_prices=price_snapshot.prices,
        target_weights=targets,
        review_note="notify flow review",
    )
    result_report = check_paper_cycle_result(result)
    print("\nchapter-23 daily_cycle")
    print(
        f"trade_date={result.snapshot.trade_date.isoformat()}",
        f"total_equity={result.snapshot.total_equity:.2f}",
        f"risk={result.risk_report.severity}",
        f"orders={len(result.rebalance_plan.orders)}",
    )

    memory_receipt = send_paper_alert(
        MemoryNotificationChannel(),
        result.alert_message,
        destination=args.destination,
        sent_at=sent_at,
    )
    print("\nchapter-26 notification_channel")
    print(
        f"channel={memory_receipt.channel}",
        f"accepted={memory_receipt.accepted}",
        f"destination={memory_receipt.destination}",
        f"title={memory_receipt.message_title}",
        f"error={memory_receipt.error or '-'}",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        notification_path = Path(tmp_dir) / "paper-alerts.jsonl"
        file_receipt = send_paper_alert(
            FileNotificationChannel(path=notification_path),
            result.alert_message,
            destination=args.destination,
            sent_at=sent_at,
        )
        rows = read_file_notifications(notification_path)

    print("\nchapter-27 file_notification")
    print(
        f"channel={file_receipt.channel}",
        f"accepted={file_receipt.accepted}",
        f"rows={len(rows)}",
        f"last_severity={rows[-1]['severity'] if rows else '-'}",
        f"last_title={rows[-1]['message_title'] if rows else '-'}",
    )

    health = build_run_health_report(
        price_snapshot=price_snapshot,
        input_check=input_report,
        result_check=result_report,
        notification_receipt=file_receipt,
    )
    print("\nchapter-30 run_health")
    print(
        f"status={health.status}",
        f"issue_count={health.issue_count}",
        f"notification_accepted={health.notification_accepted}",
        f"missing_price_count={health.missing_price_count}",
    )
    print(f"summary={health.summary}")
    return 0


def print_paper_ops_check(args: argparse.Namespace) -> int:
    trade_date = date.fromisoformat(args.trade_date)
    now = datetime.fromisoformat(args.now).replace(tzinfo=timezone.utc)
    account = PaperAccountState(cash=args.initial_cash)

    seed = apply_paper_order(
        account,
        trade_date=trade_date - timedelta(days=1),
        symbol=args.seed_symbol,
        side="buy",
        price=args.seed_price,
        shares=args.seed_shares,
    )
    if not seed.accepted:
        raise RuntimeError(f"seed order rejected: {seed.reason}")
    account = seed.account

    window = RunWindow(start=time.fromisoformat(args.window_start), end=time.fromisoformat(args.window_end))
    window_status = evaluate_run_window(now, window)
    print("chapter-31-35 paper_ops_check")
    print("\nchapter-31 run_window")
    print(
        f"now={now.isoformat()}",
        f"window={args.window_start}-{args.window_end}",
        f"allowed={window_status.allowed}",
        f"reason={window_status.reason}",
        f"next_run_at={window_status.next_run_at.isoformat() if window_status.next_run_at else '-'}",
    )

    targets = normalize_target_weights(
        build_equal_weight_targets(
            args.candidates,
            TargetWeightPolicy(max_symbols=args.max_symbols, gross_exposure=args.gross_exposure),
        ),
        max_total=args.max_total,
    )
    required_symbols = collect_required_price_symbols(list(account.positions), targets)
    provider = StaticPriceProvider(
        {
            args.seed_symbol: args.seed_last_price,
            args.extra_symbol: args.extra_last_price,
        }
    )
    price_snapshot = provider.get_last_prices(required_symbols, trade_date=trade_date)
    input_report = check_paper_cycle_inputs(account, last_prices=price_snapshot.prices, target_weights=targets)
    result = run_paper_daily_cycle(
        account,
        trade_date=trade_date,
        last_prices=price_snapshot.prices,
        target_weights=targets,
        review_note="ops checklist archive",
    )
    result_report = check_paper_cycle_result(result)
    receipt = send_paper_alert(
        MemoryNotificationChannel(),
        result.alert_message,
        destination=args.destination,
        sent_at=now,
    )
    health = build_run_health_report(
        price_snapshot=price_snapshot,
        input_check=input_report,
        result_check=result_report,
        notification_receipt=receipt,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_dir = Path(tmp_dir) / "reports"
        previous_result = run_paper_daily_cycle(
            account,
            trade_date=trade_date - timedelta(days=1),
            last_prices={args.seed_symbol: args.seed_price, args.extra_symbol: args.extra_last_price},
            target_weights=targets,
            review_note="previous blocked run",
        )
        previous_archive = archive_daily_report(
            directory=archive_dir,
            trade_date=trade_date - timedelta(days=1),
            alert_message=previous_result.alert_message,
            health_report=RunHealthReport("blocker", 1, False, 1, "previous run blocked by missing data"),
            review_record=previous_result.review_record,
        )
        current_archive = archive_daily_report(
            directory=archive_dir,
            trade_date=trade_date,
            alert_message=result.alert_message,
            health_report=health,
            review_record=result.review_record,
        )
        current_payload = read_archived_report(current_archive.path)
        history = summarize_archived_reports(archive_dir)

    print("\nchapter-32 report_archive")
    print(
        f"archived={current_archive.path.name}",
        f"status={current_archive.status}",
        f"payload_keys={sorted(current_payload)}",
    )
    print(f"previous_archive={previous_archive.path.name} status={previous_archive.status}")

    print("\nchapter-33 run_history")
    print(
        f"report_count={history.report_count}",
        f"latest_trade_date={history.latest_trade_date}",
        f"latest_status={history.latest_status}",
        f"blocker_count={history.blocker_count}",
        f"notification_success_rate={history.notification_success_rate:.2%}",
    )

    gap_provider = StaticPriceProvider({args.seed_symbol: args.seed_last_price})
    gap_snapshot = gap_provider.get_last_prices(required_symbols, trade_date=trade_date)
    gap_plan = build_price_gap_plan(gap_snapshot, required_symbols=required_symbols)
    print("\nchapter-34 data_gaps")
    print(
        f"required_symbols={required_symbols}",
        f"available_prices={sorted(gap_snapshot.prices)}",
        f"severity={gap_plan.severity}",
        f"gap_symbols={gap_symbols(gap_plan)}",
    )

    checklist = build_ops_checklist(
        window_status=window_status,
        history_summary=history,
        gap_plan=gap_plan,
        health_report=health,
    )
    print("\nchapter-35 ops_checklist")
    print(f"passed={checklist.passed} items={len(checklist.items)}")
    for item in checklist.items:
        print(f"{item.name}: passed={item.passed} detail={item.detail}")
    return 0


def print_paper_run_plan(args: argparse.Namespace) -> int:
    trade_date = date.fromisoformat(args.trade_date)
    generated_at = datetime.fromisoformat(args.generated_at).replace(tzinfo=timezone.utc)
    request = build_daily_run_request(
        trade_date=trade_date,
        generated_at=generated_at,
        required_symbols=args.required_symbols,
        dry_run=args.dry_run,
    )

    print("chapter-36-40 paper_run_plan")
    print("\nchapter-36 run_request")
    print(
        f"trade_date={request.trade_date.isoformat()}",
        f"generated_at={request.generated_at.isoformat()}",
        f"required_symbols={request.required_symbols}",
        f"symbol_count={request_symbol_count(request)}",
        f"dry_run={request.dry_run}",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_dir = Path(tmp_dir) / "reports"
        for offset, status in ((2, "ok"), (1, "blocker"), (0, "ok")):
            day = trade_date - timedelta(days=offset)
            archive_daily_report(
                directory=archive_dir,
                trade_date=day,
                alert_message=format_paper_daily_alert(
                    build_paper_account_snapshot(PaperAccountState(cash=100000.0), trade_date=day, last_prices={}),
                    evaluate_paper_risk(build_paper_account_snapshot(PaperAccountState(cash=100000.0), trade_date=day, last_prices={})),
                    build_rebalance_plan(PaperAccountState(cash=100000.0), trade_date=day, last_prices={}, target_weights={}),
                ),
                health_report=RunHealthReport(
                    status=status,
                    issue_count=1 if status == "blocker" else 0,
                    notification_accepted=status != "blocker",
                    missing_price_count=1 if status == "blocker" else 0,
                    summary=status,
                ),
                review_record=run_paper_daily_cycle(
                    PaperAccountState(cash=100000.0),
                    trade_date=day,
                    last_prices={},
                    target_weights={},
                    review_note=f"{status} archive",
                ).review_record,
            )
        index = build_report_index(archive_dir)
        latest = latest_report_entry(index)
        history = summarize_archived_reports(archive_dir)

    print("\nchapter-38 report_index")
    print(f"index_count={len(index)} latest={latest.trade_date if latest else '-'} latest_status={latest.status if latest else '-'}")
    for entry in index:
        print(f"{entry.trade_date} status={entry.status} path={entry.path.name}")

    checklist = build_ops_checklist(
        window_status=evaluate_run_window(generated_at, RunWindow(start=time(15, 10), end=time(15, 40))),
        history_summary=history,
        gap_plan=build_price_gap_plan(
            StaticPriceProvider({args.required_symbols[0]: args.first_price}).get_last_prices(list(request.required_symbols), trade_date=trade_date),
            required_symbols=list(request.required_symbols),
        ),
        health_report=RunHealthReport("ok", 0, True, 0, "ok"),
    )
    plan = build_daily_run_plan(request=request, checklist=checklist)

    print("\nchapter-37 run_result")
    print(
        f"status={plan.result.status}",
        f"dry_run={plan.result.dry_run}",
        f"failed_checks={plan.result.failed_checks}",
    )

    print("\nchapter-39 failure_actions")
    print(f"action_summary={plan.action_summary} actions={len(plan.failure_actions)}")
    for action in plan.failure_actions:
        print(f"{action.check_name}: action={action.action} severity={action.severity}")

    print("\nchapter-40 daily_run_plan")
    print(
        f"trade_date={plan.request.trade_date.isoformat()}",
        f"result={plan.result.status}",
        f"can_execute={plan_can_execute(plan)}",
        f"action_summary={plan.action_summary}",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runnable examples for ZiQuant blog chapters.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    factor = subparsers.add_parser("factor-backtest", help="Run chapter 09-12 factor/backtest chain.")
    factor.add_argument("--source", choices=["sample", "eastmoney"], default="sample")
    factor.add_argument("--symbols", nargs="+", default=["000001.SZ", "600519.SH"])
    factor.add_argument("--begin", default="20250101")
    factor.add_argument("--end", default="20251231")
    factor.add_argument("--initial-cash", type=float, default=100000.0)
    factor.add_argument("--short-window", type=int, default=5)
    factor.add_argument("--long-window", type=int, default=20)
    factor.set_defaults(func=print_factor_backtest)

    promotion = subparsers.add_parser("strategy-promotion", help="Run chapter 13-15 parameter/search/promotion chain.")
    promotion.add_argument("--source", choices=["sample", "eastmoney"], default="sample")
    promotion.add_argument("--symbols", nargs="+", default=["000001.SZ", "600519.SH"])
    promotion.add_argument("--begin", default="20250101")
    promotion.add_argument("--end", default="20251231")
    promotion.add_argument("--initial-cash", type=float, default=100000.0)
    promotion.add_argument("--short-windows", nargs="+", type=int, default=[3, 5, 8])
    promotion.add_argument("--long-windows", nargs="+", type=int, default=[15, 20, 30])
    promotion.add_argument("--position-ratios", nargs="+", type=float, default=[0.5, 0.8])
    promotion.add_argument("--top-n", type=int, default=5)
    promotion.add_argument("--baseline-short-window", type=int, default=5)
    promotion.add_argument("--baseline-long-window", type=int, default=20)
    promotion.add_argument("--baseline-position-ratio", type=float, default=0.8)
    promotion.set_defaults(func=print_strategy_promotion)

    paper = subparsers.add_parser("paper-flow", help="Run chapter 16-20 paper trading account/risk/alert chain.")
    paper.add_argument("--trade-date", default="2026-03-02")
    paper.add_argument("--initial-cash", type=float, default=100000.0)
    paper.add_argument("--symbol", default="000001.SZ")
    paper.add_argument("--buy-price", type=float, default=12.46)
    paper.add_argument("--buy-shares", type=int, default=6400)
    paper.add_argument("--last-price", type=float, default=13.25)
    paper.add_argument("--target-weight", type=float, default=0.45)
    paper.add_argument("--min-trade-value", type=float, default=1000.0)
    paper.add_argument("--max-position-weight", type=float, default=0.35)
    paper.add_argument("--min-cash-ratio", type=float, default=0.05)
    paper.add_argument("--max-exposure-ratio", type=float, default=0.95)
    paper.set_defaults(func=print_paper_flow)

    ops = subparsers.add_parser("paper-ops", help="Run chapter 21-25 recommendation/review/state/check chain.")
    ops.add_argument("--trade-date", default="2026-03-03")
    ops.add_argument("--initial-cash", type=float, default=300000.0)
    ops.add_argument("--primary-symbol", default="000001.SZ")
    ops.add_argument("--primary-buy-price", type=float, default=11.80)
    ops.add_argument("--primary-buy-shares", type=int, default=3600)
    ops.add_argument("--primary-last-price", type=float, default=12.40)
    ops.add_argument("--primary-target-weight", type=float, default=0.20)
    ops.add_argument("--secondary-symbol", default="600519.SH")
    ops.add_argument("--secondary-buy-price", type=float, default=1520.00)
    ops.add_argument("--secondary-buy-shares", type=int, default=100)
    ops.add_argument("--secondary-last-price", type=float, default=1495.00)
    ops.add_argument("--secondary-target-weight", type=float, default=0.35)
    ops.add_argument("--review-note", default="daily paper ops review")
    ops.set_defaults(func=print_paper_ops)

    notify = subparsers.add_parser("paper-notify", help="Run chapter 26-30 price/target/notification/health chain.")
    notify.add_argument("--trade-date", default="2026-03-04")
    notify.add_argument("--sent-at", default="2026-03-04T09:00:00")
    notify.add_argument("--initial-cash", type=float, default=200000.0)
    notify.add_argument("--seed-symbol", default="000001.SZ")
    notify.add_argument("--seed-price", type=float, default=11.90)
    notify.add_argument("--seed-shares", type=int, default=4000)
    notify.add_argument("--seed-last-price", type=float, default=12.20)
    notify.add_argument("--extra-symbol", default="600519.SH")
    notify.add_argument("--extra-last-price", type=float, default=1498.00)
    notify.add_argument("--candidates", nargs="+", default=["000001.SZ", "600519.SH", "000001.SZ"])
    notify.add_argument("--max-symbols", type=int, default=2)
    notify.add_argument("--gross-exposure", type=float, default=0.60)
    notify.add_argument("--min-weight", type=float, default=0.01)
    notify.add_argument("--max-total", type=float, default=0.55)
    notify.add_argument("--destination", default="paper-daily")
    notify.set_defaults(func=print_paper_notify)

    ops_check = subparsers.add_parser("paper-ops-check", help="Run chapter 31-35 run window/archive/history/gap/checklist chain.")
    ops_check.add_argument("--trade-date", default="2026-03-05")
    ops_check.add_argument("--now", default="2026-03-05T15:20:00")
    ops_check.add_argument("--window-start", default="15:10:00")
    ops_check.add_argument("--window-end", default="15:40:00")
    ops_check.add_argument("--initial-cash", type=float, default=200000.0)
    ops_check.add_argument("--seed-symbol", default="000001.SZ")
    ops_check.add_argument("--seed-price", type=float, default=11.90)
    ops_check.add_argument("--seed-shares", type=int, default=4000)
    ops_check.add_argument("--seed-last-price", type=float, default=12.25)
    ops_check.add_argument("--extra-symbol", default="600519.SH")
    ops_check.add_argument("--extra-last-price", type=float, default=1502.00)
    ops_check.add_argument("--candidates", nargs="+", default=["000001.SZ", "600519.SH"])
    ops_check.add_argument("--max-symbols", type=int, default=2)
    ops_check.add_argument("--gross-exposure", type=float, default=0.60)
    ops_check.add_argument("--max-total", type=float, default=0.55)
    ops_check.add_argument("--destination", default="paper-daily")
    ops_check.set_defaults(func=print_paper_ops_check)

    run_plan = subparsers.add_parser("paper-run-plan", help="Run chapter 36-40 request/result/index/failure/plan chain.")
    run_plan.add_argument("--trade-date", default="2026-03-06")
    run_plan.add_argument("--generated-at", default="2026-03-06T15:20:00")
    run_plan.add_argument("--required-symbols", nargs="+", default=["000001.SZ", "600519.SH", "000001.SZ"])
    run_plan.add_argument("--first-price", type=float, default=12.30)
    run_plan.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    run_plan.set_defaults(func=print_paper_run_plan)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
