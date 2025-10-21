# ABOUTME: CLI commands for controlling the sync daemon
# ABOUTME: Provides start and status commands with configuration handling

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict

import click
import structlog

from gchat_mirror.common.config import get_default_sync_config, load_config
from gchat_mirror.sync.daemon import SyncDaemon

logger = structlog.get_logger()


@click.group()
def sync() -> None:
    """Sync daemon commands."""
    return None


def _load_sync_config(config_dir: Path) -> Dict[str, Any]:
    defaults = get_default_sync_config()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    return load_config(config_path, defaults)


@sync.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the sync daemon."""
    data_dir: Path = ctx.obj["data_dir"]
    config_dir: Path = ctx.obj["config_dir"] / "sync"

    data_dir.mkdir(parents=True, exist_ok=True)

    config = _load_sync_config(config_dir)
    daemon = SyncDaemon(data_dir, config)

    try:
        daemon.start()
    except KeyboardInterrupt:
        logger.info("sync_cli_interrupt")
        daemon.stop()
    except Exception as exc:
        logger.error("sync_cli_error", error=str(exc))
        daemon.stop()
        raise


@sync.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show status information for the sync daemon."""
    data_dir: Path = ctx.obj["data_dir"]
    db_path = data_dir / "sync" / "chat.db"

    if not db_path.exists():
        click.echo("No database found. Run 'gchat-mirror sync start' first.")
        return

    click.echo(f"Database: {db_path}")
    size_mb = db_path.stat().st_size / 1024 / 1024
    click.echo(f"Size: {size_mb:.2f} MB")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM spaces")
        space_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        message_count = cursor.fetchone()[0]
    finally:
        conn.close()

    click.echo(f"Spaces: {space_count}")
    click.echo(f"Messages: {message_count}")


@sync.command()
@click.option("--space-id", help="Space ID to backfill (omit for all)")
@click.option("--days", type=int, default=365, show_default=True, help="Days of history to fetch")
@click.option("--batch-size", type=int, default=100, show_default=True, help="Messages per API call")
@click.pass_context
def backfill(ctx: click.Context, space_id: str | None, days: int, batch_size: int) -> None:
    """Backfill historical messages."""
    from gchat_mirror.sync.backfill import BackfillManager

    data_dir: Path = ctx.obj["data_dir"]
    config_dir: Path = ctx.obj["config_dir"] / "sync"

    config = _load_sync_config(config_dir)

    click.echo(f"Backfilling {days} days of history...")

    manager = BackfillManager(data_dir, config)

    if space_id:
        # Backfill single space
        click.echo(f"Space: {space_id}")
        manager.backfill_space(space_id, days, batch_size)
    else:
        # Backfill all spaces
        manager.backfill_all_spaces(days, batch_size)

    click.echo("Backfill complete!")
