# ABOUTME: Tests for database connection helper
# ABOUTME: Ensures SQLite wrapper configures and validates databases

from __future__ import annotations

from pathlib import Path

from gchat_mirror.common.database import Database


def test_database_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "mirror" / "chat.db"

    with Database(db_path) as db:
        assert db.conn is not None
        result = db.conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

        db.conn.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        db.conn.execute("INSERT INTO example (id) VALUES (1)")
        stored = db.conn.execute("SELECT id FROM example").fetchone()[0]
        assert stored == 1


def test_integrity_check_passes(tmp_path: Path) -> None:
    db_path = tmp_path / "mirror" / "chat.db"

    database = Database(db_path)
    database.connect()
    try:
        assert database.conn is not None
        database.conn.execute("CREATE TABLE sample (id INTEGER)")
        database.conn.commit()
        assert database.integrity_check() is True
    finally:
        database.close()
