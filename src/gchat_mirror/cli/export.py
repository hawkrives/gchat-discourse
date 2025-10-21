# ABOUTME: CLI commands for export destinations
# ABOUTME: Provides commands for Discourse export status and retry operations

from __future__ import annotations

import sqlite3
from pathlib import Path

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
    click.echo("Discourse exporter daemon not yet implemented (Phase 5)")
    click.echo("Use individual export commands for now.")


@discourse.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show Discourse exporter status and progress."""
    from gchat_mirror.exporters.discourse.export_state import ExportStateManager
    
    # Get database paths from context
    data_dir: Path = ctx.obj["data_dir"]
    state_db_path = data_dir / "discourse" / "state.db"
    chat_db_path = data_dir / "sync" / "chat.db"
    
    if not state_db_path.exists():
        click.echo("No Discourse state database found.")
        click.echo("Export has not been initialized yet.")
        return
    
    if not chat_db_path.exists():
        click.echo("No sync database found.")
        click.echo("Run 'gchat-mirror sync start' first.")
        return
    
    # Connect to databases
    state_conn = sqlite3.connect(state_db_path)
    chat_conn = sqlite3.connect(chat_db_path)
    
    try:
        manager = ExportStateManager(state_conn, chat_conn)
        progress = manager.get_overall_progress()
        
        click.echo("Discourse Export Progress:")
        click.echo("=" * 50)
        click.echo(f"  Spaces: {progress['completed_spaces']}/{progress['total_spaces']} completed")
        click.echo(f"  Threads: {progress['total_threads']:,}")
        click.echo(f"  Messages: {progress['total_messages']:,}")
        click.echo(f"  Attachments: {progress['total_attachments']:,}")
        click.echo(f"  Reactions: {progress['total_reactions']:,}")
        
        if progress['total_spaces'] == 0:
            click.echo()
            click.echo("No spaces have been exported yet.")
        
    finally:
        state_conn.close()
        chat_conn.close()


@discourse.command()
@click.argument('entity_type')
@click.argument('entity_id')
@click.pass_context
def retry(ctx: click.Context, entity_type: str, entity_id: str) -> None:
    """Force retry of a failed export.
    
    ENTITY_TYPE: Type of entity (thread, message, reaction, etc.)
    ENTITY_ID: Google Chat entity ID
    
    Example:
        gchat-mirror export discourse retry message msg_abc123
    """
    from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager
    from gchat_mirror.exporters.discourse.retry_config import RetryConfig
    
    # Get database paths from context
    data_dir: Path = ctx.obj["data_dir"]
    state_db_path = data_dir / "discourse" / "state.db"
    chat_db_path = data_dir / "sync" / "chat.db"
    
    if not state_db_path.exists():
        click.echo("No Discourse state database found.")
        return
    
    if not chat_db_path.exists():
        click.echo("No sync database found.")
        return
    
    # Connect to databases
    state_conn = sqlite3.connect(state_db_path)
    chat_conn = sqlite3.connect(chat_db_path)
    
    try:
        config = RetryConfig()
        manager = FailedExportManager(state_conn, chat_conn, config)
        
        # Check if entity has failed exports
        cursor = state_conn.execute("""
            SELECT COUNT(*) FROM failed_exports
            WHERE entity_type = ? AND entity_id = ?
        """, (entity_type, entity_id))
        
        count = cursor.fetchone()[0]
        
        if count == 0:
            click.echo(f"No failed exports found for {entity_type} {entity_id}")
            return
        
        # Force retry
        success = manager.force_retry(entity_type, entity_id)
        
        if success:
            click.echo(f"✓ Forced retry for {entity_type} {entity_id}")
            click.echo("The entity will be retried on next export run.")
        else:
            click.echo(f"✗ Failed to force retry for {entity_type} {entity_id}")
            click.echo("Entity may not exist in failed exports table.")
        
    finally:
        state_conn.close()
        chat_conn.close()
