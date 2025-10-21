# ABOUTME: Tests for the primary CLI entry point
# ABOUTME: Ensures global CLI options and help output behave as expected

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from gchat_mirror.cli.main import cli
from gchat_mirror.common.database import Database
from gchat_mirror.common.migrations import run_migrations


def test_cli_help_includes_core_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "GChat Mirror" in result.output
    assert "sync" in result.output
    assert "export" in result.output
    assert "clients" in result.output
    assert "integrity-check" in result.output
    assert "health" in result.output


def test_integrity_check_no_database(tmp_path: Path) -> None:
    """Test integrity-check command when no database exists."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--data-dir", str(tmp_path), "integrity-check"])

    assert result.exit_code == 0
    assert "No database found" in result.output


def test_integrity_check_clean_database(tmp_path: Path) -> None:
    """Test integrity-check command on clean database."""
    runner = CliRunner()

    # Create database with schema
    db_dir = tmp_path / "sync"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "chat.db"

    # Run migrations to create schema
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)

    # Add valid data
    db = Database(db_path)
    db.connect()
    assert db.conn is not None

    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', datetime('now'))
        """
    )
    db.conn.execute(
        """
        INSERT INTO users (id, display_name)
        VALUES ('user1', 'Test User')
        """
    )
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, sender_id, create_time)
        VALUES ('msg1', 'space1', 'test', 'user1', datetime('now'))
        """
    )
    db.conn.commit()
    db.close()

    # Run integrity check
    result = runner.invoke(cli, ["--data-dir", str(tmp_path), "integrity-check"])

    assert result.exit_code == 0
    assert "Running integrity checks" in result.output
    assert "✓ All integrity checks passed" in result.output


def test_integrity_check_detects_issues(tmp_path: Path) -> None:
    """Test integrity-check command detects issues."""
    runner = CliRunner()

    # Create database with schema
    db_dir = tmp_path / "sync"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "chat.db"

    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)

    # Add invalid data
    db = Database(db_path)
    db.connect()
    assert db.conn is not None

    db.conn.execute("PRAGMA foreign_keys=OFF")
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, sender_id, create_time)
        VALUES ('msg1', 'nonexistent', 'orphan', 'user1', datetime('now'))
        """
    )
    db.conn.commit()
    db.conn.execute("PRAGMA foreign_keys=ON")
    db.close()

    # Run integrity check
    result = runner.invoke(cli, ["--data-dir", str(tmp_path), "integrity-check"])

    assert result.exit_code == 0
    assert "✗ Integrity issues found" in result.output
    assert "orphaned_messages" in result.output


def test_health_command_daemon_not_running() -> None:
    """Test health command when daemon is not running."""
    runner = CliRunner()

    # Mock httpx to simulate connection error
    with patch("httpx.get") as mock_get:
        import httpx

        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = runner.invoke(cli, ["health"])

        assert result.exit_code == 0
        assert "Could not connect to health check endpoint" in result.output
        assert "Is the sync daemon running?" in result.output


def test_health_command_success() -> None:
    """Test health command with successful response."""
    runner = CliRunner()

    # Mock httpx response
    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "spaces_synced": 5,
            "messages_synced": 100,
            "last_sync": "2025-10-20T14:30:00+00:00",
        }
        mock_get.return_value = mock_response

        result = runner.invoke(cli, ["health"])

        assert result.exit_code == 0
        assert "Status: ok" in result.output
        assert "Spaces: 5" in result.output
        assert "Messages: 100" in result.output
        assert "Last sync: 2025-10-20T14:30:00+00:00" in result.output


def test_health_command_custom_port() -> None:
    """Test health command with custom port."""
    runner = CliRunner()

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "spaces_synced": 0,
            "messages_synced": 0,
            "last_sync": "never",
        }
        mock_get.return_value = mock_response

        result = runner.invoke(cli, ["health", "--port", "5000"])

        assert result.exit_code == 0
        mock_get.assert_called_once_with("http://localhost:5000/health", timeout=5.0)
