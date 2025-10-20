# ABOUTME: CLI commands for export destinations
# ABOUTME: Provides placeholder commands until exporters are implemented

from __future__ import annotations

import click


@click.group()
def export() -> None:
    """Export client commands."""
    return None


@export.group()
def discourse() -> None:
    """Discourse exporter commands."""
    return None


@discourse.command()
def start() -> None:
    """Start the Discourse exporter."""
    click.echo("Discourse exporter not yet implemented (Phase 4)")


@discourse.command()
def status() -> None:
    """Show Discourse exporter status."""
    click.echo("Discourse exporter not yet implemented (Phase 4)")
