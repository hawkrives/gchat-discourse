# ABOUTME: Tests for export client registry management
# ABOUTME: Verifies client registration, heartbeats, and status tracking

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.client_registry import ClientRegistry
from gchat_mirror.common.migrations import run_migrations


@pytest.fixture
def client_registry(tmp_path: Path) -> ClientRegistry:
    """Create a ClientRegistry with proper schema."""
    db_path = tmp_path / "chat.db"
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    return ClientRegistry(conn)


def test_client_registry_register(client_registry: ClientRegistry) -> None:
    """Test client registration."""
    # Register client
    client_id = client_registry.register(
        "discourse-1", "discourse", {"url": "https://discourse.example.com"}
    )
    assert client_id == "discourse-1"

    # List clients
    clients = client_registry.list_clients()
    assert len(clients) == 1
    assert clients[0]["id"] == "discourse-1"
    assert clients[0]["status"] == "active"


def test_client_registry_heartbeat(client_registry: ClientRegistry) -> None:
    """Test client heartbeat updates."""
    # Register client
    client_registry.register("discourse-1", "discourse")

    # Heartbeat
    client_registry.heartbeat("discourse-1", last_processed_notification=42)

    # Verify heartbeat updated
    cursor = client_registry.conn.execute(
        """
        SELECT last_processed_notification FROM export_clients 
        WHERE id = 'discourse-1'
        """
    )
    assert cursor.fetchone()[0] == 42


def test_client_registry_unregister(client_registry: ClientRegistry) -> None:
    """Test client unregistration."""
    # Register client
    client_registry.register("discourse-1", "discourse")

    # Unregister
    client_registry.unregister("discourse-1")

    clients = client_registry.list_clients()
    assert clients[0]["status"] == "inactive"


def test_client_registry_reregister_reactivates(
    client_registry: ClientRegistry,
) -> None:
    """Test that re-registering an inactive client reactivates it."""
    # Register and unregister
    client_registry.register("discourse-1", "discourse")
    client_registry.unregister("discourse-1")

    # Re-register
    client_registry.register("discourse-1", "discourse")

    clients = client_registry.list_clients()
    assert clients[0]["status"] == "active"
