# ABOUTME: Tests for SQLite migration runner utilities
# ABOUTME: Verifies migration tracking and execution logic

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.migrations import (
    apply_migration,
    get_applied_migrations,
    run_migrations,
)


@pytest.fixture
def empty_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _write_migration(migrations_dir: Path, version: str, body: str) -> Path:
    path = migrations_dir / f"{version}.py"
    path.write_text(
        "# ABOUTME: Ad-hoc test migration\n"
        "# ABOUTME: Created within unit test to exercise migration logic\n"
        "\n"
        "def upgrade(conn):\n"
        f"    {body}\n"
    )
    return path


def test_get_applied_migrations_returns_versions(empty_db: sqlite3.Connection, tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    first = _write_migration(migrations_dir, "001_initial", "conn.execute(\"CREATE TABLE foo (id INTEGER)\")")

    # Before applying, no rows should exist
    assert get_applied_migrations(empty_db) == []

    apply_migration(empty_db, first)
    assert get_applied_migrations(empty_db) == ["001_initial"]


def test_run_migrations_applies_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / "mirror.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    _write_migration(
        migrations_dir,
        "001_create_table",
        "conn.execute(\"CREATE TABLE alpha (id INTEGER PRIMARY KEY)\")",
    )
    _write_migration(
        migrations_dir,
        "002_insert_row",
        "conn.execute(\"INSERT INTO alpha (id) VALUES (1)\")",
    )

    run_migrations(db_path, migrations_dir)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alpha'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute("SELECT COUNT(*) FROM alpha")
        assert cursor.fetchone()[0] == 1

        cursor = conn.execute("SELECT COUNT(*) FROM schema_migrations")
        assert cursor.fetchone()[0] == 2

        applied = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in applied] == ["001_create_table", "002_insert_row"]

        # Run again to confirm idempotency
        run_migrations(db_path, migrations_dir)
        cursor = conn.execute("SELECT COUNT(*) FROM schema_migrations")
        assert cursor.fetchone()[0] == 2
    finally:
        conn.close()
