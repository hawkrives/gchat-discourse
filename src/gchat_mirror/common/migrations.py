# ABOUTME: Database migration system for tracking and applying schema changes
# ABOUTME: Manages sequential migration scripts and records applied migrations

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from typing import List

import structlog

logger = structlog.get_logger()


def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """Return list of applied migration names."""
    _ensure_migrations_table(conn)
    cursor = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )
    return [row[0] for row in cursor.fetchall()]


def apply_migration(conn: sqlite3.Connection, migration_path: Path) -> None:
    """Apply a single migration script."""
    _ensure_migrations_table(conn)
    version = migration_path.stem

    spec = importlib.util.spec_from_file_location(version, migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration module from {migration_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "upgrade"):
        raise AttributeError(f"Migration {migration_path} missing upgrade() function")

    module.upgrade(conn)
    conn.execute(
        "INSERT INTO schema_migrations (version) VALUES (?)",
        (version,),
    )
    conn.commit()


def run_migrations(db_path: Path, migrations_dir: Path) -> None:
    """Run all pending migrations."""
    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory {migrations_dir} does not exist")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        applied = set(get_applied_migrations(conn))

        migration_files = sorted(
            path for path in migrations_dir.iterdir() if path.suffix == ".py"
        )

        for migration_path in migration_files:
            version = migration_path.stem
            if version in applied:
                continue
            apply_migration(conn, migration_path)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def get_discourse_migrations_dir() -> Path:
    """Get path to discourse migrations directory."""
    return Path(__file__).parent.parent.parent.parent / "migrations" / "discourse"


def run_discourse_migrations(conn: sqlite3.Connection) -> None:
    """
    Run discourse exporter migrations.
    
    Args:
        conn: Connection to exporter state database
    """
    migrations_dir = get_discourse_migrations_dir()
    
    if not migrations_dir.exists():
        logger.info("no_discourse_migrations_found")
        return
    
    # Create migrations table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    # Get applied migrations
    cursor = conn.execute("SELECT version FROM schema_migrations")
    applied = {row[0] for row in cursor.fetchall()}
    
    # Find migration files
    migration_files = sorted(
        path for path in migrations_dir.iterdir() 
        if path.suffix == ".py" and not path.name.startswith("_")
    )
    
    for migration_file in migration_files:
        version = migration_file.stem
        
        if version in applied:
            continue
        
        logger.info("running_discourse_migration", version=version)
        
        # Load and run migration
        spec = importlib.util.spec_from_file_location(version, migration_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load migration from {migration_file}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, "upgrade"):
            raise AttributeError(f"Migration {migration_file} missing upgrade() function")
        
        # Run upgrade
        module.upgrade(conn)
        
        # Record migration
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (version,)
        )
        conn.commit()
        
        logger.info("discourse_migration_complete", version=version)
