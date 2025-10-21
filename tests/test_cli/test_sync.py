# ABOUTME: Tests for sync CLI commands
# ABOUTME: Validates start and status behavior for the sync group

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict

import pytest  # type: ignore
from click.testing import CliRunner

from gchat_mirror.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_sync_start_invokes_daemon_with_loaded_config(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"

    sync_dir = config_dir / "sync"
    sync_dir.mkdir(parents=True)
    (sync_dir / "config.toml").write_text(
        """
[auth]
credential_key = "custom-key"

[sync]
initial_sync_days = 10
        """.strip()
    )

    monkeypatch.setenv("GCHAT_MIRROR_SYNC_INITIAL_SYNC_DAYS", "42")

    captured: Dict[str, Any] = {}

    class FakeDaemon:
        def __init__(self, directory: Path, config: Dict[str, Any]) -> None:
            captured["data_dir"] = directory
            captured["config"] = config
            captured["started"] = False
            captured["running"] = False

        def start(self) -> None:
            captured["started"] = True

        def run_forever(self) -> None:
            captured["running"] = True

        def stop(self) -> None:
            captured["stopped"] = True

    monkeypatch.setattr("gchat_mirror.cli.sync.SyncDaemon", FakeDaemon)

    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "--config-dir",
            str(config_dir),
            "sync",
            "start",
        ],
    )

    assert result.exit_code == 0
    assert captured["started"] is True
    assert Path(captured["data_dir"]) == data_dir
    assert captured["config"]["auth"]["credential_key"] == "custom-key"
    assert captured["config"]["sync"]["initial_sync_days"] == 42


def test_sync_status_reports_database_counts(tmp_path: Path, runner: CliRunner) -> None:
    data_dir = tmp_path / "data"
    db_path = data_dir / "sync" / "chat.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE spaces (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO spaces (id) VALUES ('space1')")
        conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "sync",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "Database:" in result.output
    assert "Spaces: 1" in result.output
    assert "Messages: 1" in result.output


def test_sync_status_handles_missing_database(tmp_path: Path, runner: CliRunner) -> None:
    data_dir = tmp_path / "data"

    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "sync",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "No database found" in result.output
