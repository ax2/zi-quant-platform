from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.report_archive import read_archived_report


@dataclass(frozen=True)
class ReportIndexEntry:
    trade_date: str
    status: str
    path: Path


def build_report_index(directory: str | Path) -> tuple[ReportIndexEntry, ...]:
    entries: list[ReportIndexEntry] = []
    for path in sorted(Path(directory).glob("*-paper-report.json")):
        payload = read_archived_report(path)
        entries.append(
            ReportIndexEntry(
                trade_date=payload["trade_date"],
                status=payload["health"]["status"],
                path=path,
            )
        )
    return tuple(entries)


def latest_report_entry(entries: tuple[ReportIndexEntry, ...]) -> ReportIndexEntry | None:
    if not entries:
        return None
    return entries[-1]
