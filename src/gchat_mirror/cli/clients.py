# ABOUTME: Placeholder for client management CLI commands
# ABOUTME: Provides group definition for managing exporters

from __future__ import annotations

import click


@click.group()
def clients() -> None:
    """Export client management."""
    return None
