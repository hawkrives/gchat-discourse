# ABOUTME: Tests for client management CLI placeholders
# ABOUTME: Ensures client commands exist and respond with placeholder output

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from gchat_mirror.cli.main import cli


def test_clients_list_placeholder(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "clients",
            "list",
        ],
    )

    assert result.exit_code == 0
    assert "Client management not yet implemented" in result.output


def test_clients_unregister_placeholder(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "clients",
            "unregister",
            "exporter-1",
        ],
    )

    assert result.exit_code == 0
    assert "Client management not yet implemented" in result.output
