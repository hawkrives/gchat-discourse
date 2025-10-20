# ABOUTME: CLI commands for export client management
# ABOUTME: Provides placeholder commands for future functionality

from __future__ import annotations

import click


@click.group()
def clients() -> None:
    """Export client management."""
    return None


@clients.command()
def list() -> None:
    """List registered export clients."""
    click.echo("Client management not yet implemented (Phase 2)")


@clients.command()
@click.argument("client_id")
def unregister(client_id: str) -> None:
    """Unregister an export client."""
    click.echo("Client management not yet implemented (Phase 2)")
