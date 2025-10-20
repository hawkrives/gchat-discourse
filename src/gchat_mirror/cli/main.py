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


if __name__ == "__main__":
    cli()
