from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from app.settings import settings


def _pg_url(database_url: str) -> str:
    if database_url.startswith("postgresql+"):
        return "postgresql://" + database_url.split("://", 1)[1]
    if database_url.startswith("postgres+"):
        return "postgres://" + database_url.split("://", 1)[1]
    return database_url


def _split_netloc(netloc: str) -> tuple[str, str | None, str]:
    if "@" not in netloc:
        return "", None, netloc
    auth, host = netloc.rsplit("@", 1)
    if ":" not in auth:
        return unquote(auth), None, host
    user, password = auth.split(":", 1)
    return unquote(user), unquote(password), host


def _dbname_url_without_password(database_url: str) -> tuple[str, str | None, str]:
    parsed = urlsplit(_pg_url(database_url))
    user, password, host = _split_netloc(parsed.netloc)
    if user:
        safe_netloc = f"{quote(user, safe='')}@{host}"
    else:
        safe_netloc = host
    dbname = urlunsplit((parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment))
    redacted_netloc = f"{quote(user, safe='')}:***@{host}" if user and password else parsed.netloc
    redacted = urlunsplit((parsed.scheme, redacted_netloc, parsed.path, parsed.query, parsed.fragment))
    return dbname, password, redacted


def build_pg_dump_command(database_url: str, output_path: Path, jobs: int = 1) -> tuple[list[str], dict[str, str], str]:
    dbname, password, redacted = _dbname_url_without_password(database_url)
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output_path),
        "--dbname",
        dbname,
    ]
    env = {}
    if password:
        env["PGPASSWORD"] = password
    return command, env, redacted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(
    database_url: str,
    output_dir: Path,
    prefix: str = "zi_quant",
    jobs: int = 1,
    dry_run: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    output_path = output_dir / f"{prefix}_{created_at.strftime('%Y%m%dT%H%M%SZ')}.dump"
    command, sensitive_env, redacted_url = build_pg_dump_command(database_url, output_path, jobs=jobs)
    safe_command = ["***redacted***" if item == sensitive_env.get("PGPASSWORD") else item for item in command]
    manifest = {
        "status": "dry_run" if dry_run else "running",
        "created_at": created_at.isoformat(),
        "output_path": str(output_path),
        "database_url": redacted_url,
        "command": safe_command,
        "format": "pg_dump_custom",
        "requested_jobs": jobs,
        "effective_jobs": 1,
        "paper_only": True,
        "warning": "数据库备份只读取平台数据，不提交真实交易订单，不构成投资建议。",
    }
    if dry_run:
        return manifest
    env = os.environ.copy()
    env.update(sensitive_env)
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    manifest["returncode"] = result.returncode
    manifest["stderr_tail"] = result.stderr[-2000:] if result.stderr else ""
    if result.returncode == 0 and output_path.exists():
        manifest.update({
            "status": "success",
            "size_bytes": output_path.stat().st_size,
            "sha256": _sha256(output_path),
        })
    else:
        manifest["status"] = "failed"
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a pg_dump backup for ZiQuant PostgreSQL database.")
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--output-dir", default=os.getenv("ZI_BACKUP_DIR", "backups"))
    parser.add_argument("--prefix", default="zi_quant")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = backup_database(
        args.database_url,
        Path(args.output_dir),
        prefix=args.prefix,
        jobs=max(1, args.jobs),
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
