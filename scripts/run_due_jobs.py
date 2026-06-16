from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from app.db import SessionLocal
from app.services import run_due_data_jobs, seed_database


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _next_sleep_seconds(now: datetime | None = None, interval_seconds: int = 60) -> float:
    interval = max(int(interval_seconds), 1)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    elapsed = current.timestamp() % interval
    delay = interval - elapsed
    return float(delay if delay > 0 else interval)


async def _run_once(now: datetime | None, limit: int) -> dict[str, Any]:
    async with SessionLocal() as session:
        await seed_database(session)
        return await run_due_data_jobs(session, now=now, limit=limit)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


async def _run_loop(limit: int, interval_seconds: int, max_iterations: int | None = None) -> None:
    iteration = 0
    while True:
        iteration += 1
        result = await _run_once(now=None, limit=limit)
        _print_json({
            "runner": "zi-quant-run-due-jobs",
            "mode": "loop",
            "iteration": iteration,
            "ran_at": datetime.now(UTC).isoformat(),
            "paper_only": True,
            "result": result,
        })
        if max_iterations is not None and iteration >= max_iterations:
            break
        await asyncio.sleep(_next_sleep_seconds(interval_seconds=interval_seconds))


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Run ZiQuant data jobs whose cron schedule is due.")
    parser.add_argument("--now", help="Override current time as ISO datetime for testing, e.g. 2026-06-11T16:00:00+08:00")
    parser.add_argument("--limit", type=int, default=5, help="Maximum due jobs to run in one invocation.")
    parser.add_argument("--loop", action="store_true", help="Run continuously and poll due jobs every interval.")
    parser.add_argument("--interval-seconds", type=int, default=60, help="Loop polling interval in seconds.")
    parser.add_argument("--max-iterations", type=int, help="Stop loop after N iterations; useful for smoke tests.")
    args = parser.parse_args()
    if args.loop and args.now:
        parser.error("--now cannot be used with --loop; loop mode always uses wall-clock time.")
    if args.loop:
        await _run_loop(limit=args.limit, interval_seconds=args.interval_seconds, max_iterations=args.max_iterations)
        return
    _print_json(await _run_once(now=_parse_now(args.now), limit=args.limit))


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
