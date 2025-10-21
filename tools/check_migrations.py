"""Run migrations in `migrations/` against a temporary sqlite database and report schema.

This script imports migration modules that expose `upgrade(conn)` and executes them
in numeric order (by filename). Intended as a local developer tool to validate migrations.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path


def load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None:
        raise RuntimeError(f"Could not load migration spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    if spec.loader is None:
        raise RuntimeError(f"No loader for migration {path}")
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def main():
    repo_root = Path(__file__).resolve().parents[1]
    migrations_dir = repo_root / "migrations"
    if not migrations_dir.exists():
        print("No migrations/ directory found", file=sys.stderr)
        sys.exit(1)

    files = sorted(p for p in migrations_dir.iterdir() if p.name.endswith(".py"))
    if not files:
        print("No migration files found", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_migrations.db"
        conn = sqlite3.connect(str(db_path))
        try:
            for f in files:
                print(f"Applying {f.name}...", file=sys.stderr)
                mod = load_migration(f)
                if hasattr(mod, "upgrade"):
                    mod.upgrade(conn)
                else:
                    print(f"Migration {f.name} has no upgrade(conn) function", file=sys.stderr)

            print("\nFinal tables and schema:\n")
            cur = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
            for name, sql in cur.fetchall():
                print(f"-- {name}\n{sql}\n")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
