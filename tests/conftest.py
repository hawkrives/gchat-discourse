from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from gchat_mirror.common.database import Database
from gchat_mirror.common.migrations import run_migrations


@pytest.fixture
def db(chat_db) -> Generator[Database, None, None]:
    return chat_db


@pytest.fixture
def chat_db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test chat database with full migrations applied and yield Database manager.

    This central fixture should be used by tests that need a migrated database
    and a connected Database manager. It ensures consistent setup and cleanup.
    """
    db_path = tmp_path / "chat.db"
    migrations_dir = Path(__file__).parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)

    manager = Database(db_path)
    manager.connect()
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture
def attachments_db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test attachments database with full migrations applied and yield Database manager.

    This central fixture should be used by tests that need a migrated database
    and a connected Database manager. It ensures consistent setup and cleanup.
    """
    db_path = tmp_path / "attachments.db"
    migrations_dir = Path(__file__).parent.parent / "migrations" / "attachments"
    run_migrations(db_path, migrations_dir)

    manager = Database(db_path)
    manager.connect()
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture
def discourse_state_db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a Discourse exporter state database with production schema."""
    db_path = tmp_path / "state.db"
    migrations_dir = Path(__file__).parent.parent / "migrations" / "discourse"
    run_migrations(db_path, migrations_dir)

    manager = Database(db_path)
    manager.connect()
    try:
        yield manager
    finally:
        manager.close()
