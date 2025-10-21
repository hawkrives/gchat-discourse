# ABOUTME: Main entry point for command-line interface
# ABOUTME: Sets up global options, logging, and subcommand wiring

from __future__ import annotations

from pathlib import Path

import click

from gchat_mirror.common.logging import configure_logging
from gchat_mirror.cli import clients, export, sync


def _resolve_path(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@click.group()
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=lambda: Path.home() / ".local" / "share" / "gchat-mirror",
    help="Data directory for databases and runtime state",
)
@click.option(
    "--config-dir",
    type=click.Path(path_type=Path),
    default=lambda: Path.home() / ".config" / "gchat-mirror",
    help="Directory for configuration files",
)
@click.option("--debug", is_flag=True, help="Enable debug logging output")
@click.pass_context
def cli(ctx: click.Context, data_dir: Path, config_dir: Path, debug: bool) -> None:
    """GChat Mirror - Mirror Google Chat to SQLite and export data."""
    configure_logging(debug=debug)

    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = _resolve_path(data_dir)
    ctx.obj["config_dir"] = _resolve_path(config_dir)
    ctx.obj["debug"] = debug


cli.add_command(sync.sync)
cli.add_command(export.export)
cli.add_command(clients.clients)


@cli.command()
@click.pass_context
def integrity_check(ctx: click.Context) -> None:
    """Run database integrity checks."""
    import sqlite3

    from gchat_mirror.common.integrity import IntegrityChecker

    data_dir: Path = ctx.obj["data_dir"]
    db_path = data_dir / "sync" / "chat.db"

    if not db_path.exists():
        click.echo("No database found.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    checker = IntegrityChecker(conn)

    click.echo("Running integrity checks...")

    if checker.check_all():
        click.echo("✓ All integrity checks passed")
    else:
        click.echo("✗ Integrity issues found:")
        for issue in checker.issues:
            click.echo(f"  - {issue['type']}: {issue}")

    conn.close()


@cli.command()
@click.option("--port", default=4981, help="Health check port")
@click.pass_context
def health(ctx: click.Context, port: int) -> None:
    """Query health check endpoint."""
    import httpx

    try:
        response = httpx.get(f"http://localhost:{port}/health", timeout=5.0)

        if response.status_code == 200:
            data = response.json()
            click.echo(f"Status: {data['status']}")
            click.echo(f"Spaces: {data['spaces_synced']}")
            click.echo(f"Messages: {data['messages_synced']}")
            click.echo(f"Last sync: {data['last_sync']}")
        else:
            click.echo(f"Health check failed: HTTP {response.status_code}")

    except httpx.ConnectError:
        click.echo("Could not connect to health check endpoint.")
        click.echo("Is the sync daemon running?")
    except Exception as e:
        click.echo(f"Error: {e}")


if __name__ == "__main__":
    cli()
