from __future__ import annotations

from pathlib import Path

from scripts.db_backup import backup_database, build_pg_dump_command


def test_build_pg_dump_command_redacts_password_from_command():
    command, env, redacted = build_pg_dump_command(
        "postgresql+asyncpg://zi_quant:example-pass@127.0.0.1:5432/zi_quant",
        Path("/tmp/backup.dump"),
    )

    command_text = " ".join(command)
    assert "postgresql://zi_quant@127.0.0.1:5432/zi_quant" in command_text
    assert "example-pass" not in command_text
    assert env == {"PGPASSWORD": "example-pass"}
    assert redacted == "postgresql://zi_quant:***@127.0.0.1:5432/zi_quant"


def test_backup_database_dry_run_writes_no_secret_to_manifest(tmp_path):
    report = backup_database(
        "postgresql+asyncpg://zi_quant:example-pass@127.0.0.1:5432/zi_quant",
        tmp_path,
        dry_run=True,
    )

    assert report["status"] == "dry_run"
    assert report["paper_only"] is True
    assert str(tmp_path) in report["output_path"]
    assert "example-pass" not in str(report)
