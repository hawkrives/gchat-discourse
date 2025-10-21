# ABOUTME: Database connection management and common SQL operations
# ABOUTME: Provides connection helpers for SQLite access across modules

from __future__ import annotations

import sqlite3
import datetime
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()


def adapt_date_iso(val):
    """Adapt datetime.date to ISO 8601 date."""
    return val.isoformat()


def adapt_datetime_iso(val):
    """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
    return val.replace(tzinfo=None).isoformat()


def adapt_datetime_epoch(val):
    """Adapt datetime.datetime to Unix timestamp."""
    return int(val.timestamp())


sqlite3.register_adapter(datetime.date, adapt_date_iso)
sqlite3.register_adapter(datetime.datetime, adapt_datetime_iso)
sqlite3.register_adapter(datetime.datetime, adapt_datetime_epoch)


def convert_date(val):
    """Convert ISO 8601 date to datetime.date object."""
    return datetime.date.fromisoformat(val.decode())


def convert_datetime(val):
    """Convert ISO 8601 datetime to datetime.datetime object."""
    return datetime.datetime.fromisoformat(val.decode())


def convert_timestamp(val):
    """Convert Unix epoch timestamp to datetime.datetime object."""
    return datetime.datetime.fromtimestamp(int(val))


sqlite3.register_converter("date", convert_date)
sqlite3.register_converter("datetime", convert_datetime)
sqlite3.register_converter("timestamp", convert_timestamp)


class Database:
    """Manage database connection and operations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Open database connection with optimizations."""
        if self.conn is not None:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        pragmas = [
            ("PRAGMA journal_mode=WAL", "wal"),
            ("PRAGMA synchronous=NORMAL", None),
            ("PRAGMA cache_size=-64000", None),
            ("PRAGMA foreign_keys=ON", None),
        ]

        for statement, expected in pragmas:
            cursor = self.conn.execute(statement)
            if expected is not None:
                cursor_value = cursor.fetchone()
                if cursor_value is None or cursor_value[0].lower() != expected:
                    raise RuntimeError(
                        f"Failed to set pragma {statement} to expected value {expected}"
                    )

        logger.debug("database_connected", path=str(self.db_path))

    def close(self) -> None:
        """Close database connection."""
        if self.conn is None:
            return

        self.conn.close()
        self.conn = None
        logger.debug("database_closed", path=str(self.db_path))

    def integrity_check(self) -> bool:
        """Run PRAGMA integrity_check."""
        if self.conn is None:
            raise RuntimeError("Database connection not open")

        cursor = self.conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        return bool(result and result[0].lower() == "ok")

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
