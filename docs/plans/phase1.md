# Phase 1: Basic Sync - Detailed Specification

## Goal

Get messages from Google Chat into SQLite with proper authentication, basic sync loop, and CLI interface.

## Duration

2-3 weeks

## Prerequisites

- Python 3.11+
- uv installed
- Google Cloud project with Chat API enabled
- OAuth credentials

## Tasks

### 1. Project Setup

#### 1.1 Initialize Repository

**Test**: Repository exists with proper structure

```bash
# Actions
git init gchat-mirror
cd gchat-mirror
uv init
```

**Files to create**:

- `.gitignore` (Python, IDE files, **pycache**, *.db, *.toml in config dirs)
- `README.md` (basic project description)
- `CLAUDE.md` (copy the development guidelines)

#### 1.2 Configure pyproject.toml

**Test**: `uv sync` works and installs dependencies

```toml
[project]
name = "gchat-mirror"
version = "0.1.0"
description = "Mirror Google Chat to SQLite and export to various destinations"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.25.0",
    "structlog>=23.2.0",
    "rich>=13.7.0",
    "click>=8.1.7",
    "google-auth>=2.24.0",
    "google-auth-oauthlib>=1.1.0",
    "google-auth-httplib2>=0.1.1",
    "keyring>=24.3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.3",
    "pytest-asyncio>=0.21.1",
    "pytest-mock>=3.12.0",
    "vcrpy>=5.1.0",
    "black>=23.11.0",
    "ruff>=0.1.6",
]

[project.scripts]
gchat-mirror = "gchat_mirror.cli.main:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]

[tool.black]
line-length = 100
target-version = ['py311']

[tool.ruff]
line-length = 100
target-version = "py311"
```

#### 1.3 Create Directory Structure

**Test**: All directories exist

```bash
mkdir -p src/gchat_mirror/{sync,exporters/discourse,common,cli}
mkdir -p tests/{fixtures,test_sync,test_exporters,test_common}
mkdir -p migrations
mkdir -p docs
```

Create `__init__.py` in each package directory.

### 2. Database Schema (chat.db)

#### 2.1 Create Migration System

**Test**: Can run migrations and track applied ones

**File**: `src/gchat_mirror/common/migrations.py`

```python
# ABOUTME: Database migration system for tracking and applying schema changes
# ABOUTME: Manages sequential migration scripts and records applied migrations

import sqlite3
from pathlib import Path
from typing import List
import importlib.util

def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """Return list of applied migration names."""
    pass

def apply_migration(conn: sqlite3.Connection, migration_path: Path):
    """Apply a single migration script."""
    pass

def run_migrations(db_path: Path, migrations_dir: Path):
    """Run all pending migrations."""
    pass
```

**File**: `migrations/001_initial_chat.py`

```python
# ABOUTME: Initial database schema for Google Chat mirror
# ABOUTME: Creates core tables: spaces, users, memberships, messages

def upgrade(conn):
    """Apply this migration."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE TABLE spaces (
            id TEXT PRIMARY KEY,
            name TEXT,
            display_name TEXT,
            space_type TEXT,
            threaded BOOLEAN,
            
            last_synced_at TIMESTAMP,
            last_message_time TIMESTAMP,
            sync_cursor TEXT,
            sync_status TEXT DEFAULT 'active',
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add indexes, other tables (users, memberships, messages, etc.)
    # See master plan for complete schema
    
    conn.commit()

def downgrade(conn):
    """Revert this migration (optional for now)."""
    pass
```

**Test**:

```python
def test_migrations_create_tables(tmp_path):
    """Test that running migrations creates expected tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    # Run migration
    from migrations import 001_initial_chat
    001_initial_chat.upgrade(conn)
    
    # Verify tables exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    
    assert 'spaces' in tables
    assert 'users' in tables
    assert 'messages' in tables
    assert 'schema_migrations' in tables
```

#### 2.2 Database Access Layer

**Test**: Can open connections, create tables, CRUD operations work

**File**: `src/gchat_mirror/common/database.py`

```python
# ABOUTME: Database connection management and common SQL operations
# ABOUTME: Provides connection pooling and helper functions for database access

import sqlite3
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()

class Database:
    """Manage database connection and operations."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    def connect(self):
        """Open database connection with optimizations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        
        # Performance tuning
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-64000")  # 64MB
        
        logger.info("database_connected", path=str(self.db_path))
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("database_closed")
    
    def integrity_check(self) -> bool:
        """Run PRAGMA integrity_check."""
        pass
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

**Test**:

```python
def test_database_connection(tmp_path):
    """Test database connection and configuration."""
    db_path = tmp_path / "test.db"
    
    with Database(db_path) as db:
        # Verify WAL mode
        result = db.conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == 'wal'
        
        # Can execute query
        db.conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        db.conn.execute("INSERT INTO test (id) VALUES (1)")
        result = db.conn.execute("SELECT id FROM test").fetchone()
        assert result[0] == 1
```

### 3. Google Chat Authentication

#### 3.1 OAuth Flow

**Test**: Can authenticate and store credentials

**File**: `src/gchat_mirror/sync/auth.py`

```python
# ABOUTME: Google OAuth authentication and credential management
# ABOUTME: Handles OAuth flow, token refresh, and keychain storage

import json
import keyring
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import structlog

logger = structlog.get_logger()

SCOPES = [
    'https://www.googleapis.com/auth/chat.spaces.readonly',
    'https://www.googleapis.com/auth/chat.messages.readonly',
    'https://www.googleapis.com/auth/chat.memberships.readonly',
]

def authenticate(credential_key: str = "gchat-sync") -> Credentials:
    """
    Authenticate with Google Chat API.
    
    Returns valid credentials, either from keychain or new OAuth flow.
    """
    # Try to load from keychain
    creds = load_credentials(credential_key)
    
    if creds and creds.valid:
        return creds
    
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(credential_key, creds)
        return creds
    
    # Run OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secrets.json', SCOPES
    )
    creds = flow.run_local_server(port=0)
    save_credentials(credential_key, creds)
    
    logger.info("authentication_complete")
    return creds

def load_credentials(credential_key: str) -> Optional[Credentials]:
    """Load credentials from system keychain."""
    pass

def save_credentials(credential_key: str, creds: Credentials):
    """Save credentials to system keychain."""
    pass
```

**Test**:

```python
def test_save_and_load_credentials(monkeypatch):
    """Test credential storage and retrieval."""
    # Mock keyring
    storage = {}
    monkeypatch.setattr(keyring, 'set_password', 
                       lambda s, k, v: storage.__setitem__(k, v))
    monkeypatch.setattr(keyring, 'get_password',
                       lambda s, k: storage.get(k))
    
    # Create mock credentials
    creds = Credentials(
        token="test_token",
        refresh_token="test_refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test_client_id",
        client_secret="test_secret"
    )
    
    # Save and load
    save_credentials("test-key", creds)
    loaded = load_credentials("test-key")
    
    assert loaded.token == "test_token"
    assert loaded.refresh_token == "test_refresh"
```

#### 3.2 Google Chat API Client

**Test**: Can fetch spaces and messages

**File**: `src/gchat_mirror/sync/google_client.py`

```python
# ABOUTME: Google Chat API client wrapper
# ABOUTME: Provides methods for fetching spaces, messages, and memberships

import httpx
from google.oauth2.credentials import Credentials
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger()

class GoogleChatClient:
    """Client for Google Chat API."""
    
    BASE_URL = "https://chat.googleapis.com/v1"
    
    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers=self._get_headers(),
            timeout=30.0
        )
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.credentials.token}"
        }
    
    def list_spaces(self) -> List[Dict[str, Any]]:
        """Fetch all spaces the user is a member of."""
        pass
    
    def list_messages(
        self, 
        space_id: str,
        page_token: Optional[str] = None,
        page_size: int = 100
    ) -> Dict[str, Any]:
        """
        Fetch messages from a space.
        
        Returns dict with 'messages' list and 'nextPageToken' if more exist.
        """
        pass
    
    def get_message(self, message_id: str) -> Dict[str, Any]:
        """Fetch a single message."""
        pass
    
    def close(self):
        """Close HTTP client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

**Test** (with mocked responses):

```python
def test_list_spaces(httpx_mock):
    """Test fetching spaces from API."""
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces",
        json={
            "spaces": [
                {
                    "name": "spaces/AAAA",
                    "displayName": "Test Space",
                    "type": "SPACE"
                }
            ]
        }
    )
    
    creds = Mock(token="test_token")
    client = GoogleChatClient(creds)
    
    spaces = client.list_spaces()
    
    assert len(spaces) == 1
    assert spaces[0]["name"] == "spaces/AAAA"
```

### 4. Basic Sync Loop

#### 4.1 Storage Layer for Sync

**Test**: Can insert/update spaces, messages, users

**File**: `src/gchat_mirror/sync/storage.py`

```python
# ABOUTME: Data storage operations for sync daemon
# ABOUTME: Handles inserting and updating spaces, messages, users in database

import sqlite3
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()

class SyncStorage:
    """Handle storage operations for sync daemon."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert_space(self, space_data: Dict[str, Any]):
        """Insert or update a space."""
        pass
    
    def upsert_user(self, user_data: Dict[str, Any]):
        """Insert or update a user."""
        pass
    
    def insert_message(self, message_data: Dict[str, Any]):
        """Insert a message (does not update existing)."""
        pass
    
    def get_space_sync_cursor(self, space_id: str) -> Optional[str]:
        """Get the last sync cursor for a space."""
        pass
    
    def update_space_sync_cursor(self, space_id: str, cursor: str):
        """Update sync cursor for a space."""
        pass
```

**Test**:

```python
def test_upsert_space(tmp_path):
    """Test space insertion and update."""
    db = setup_test_database(tmp_path)
    storage = SyncStorage(db.conn)
    
    space_data = {
        "id": "spaces/TEST",
        "name": "Test Space",
        "space_type": "SPACE",
        "raw_data": json.dumps({"full": "data"})
    }
    
    # Insert
    storage.upsert_space(space_data)
    result = db.conn.execute(
        "SELECT name FROM spaces WHERE id = ?", 
        ("spaces/TEST",)
    ).fetchone()
    assert result["name"] == "Test Space"
    
    # Update
    space_data["name"] = "Updated Space"
    storage.upsert_space(space_data)
    result = db.conn.execute(
        "SELECT name FROM spaces WHERE id = ?",
        ("spaces/TEST",)
    ).fetchone()
    assert result["name"] == "Updated Space"
```

#### 4.2 Sync Daemon

**Test**: Can run sync for one space, processes all messages

**File**: `src/gchat_mirror/sync/daemon.py`

```python
# ABOUTME: Main sync daemon that coordinates polling and data storage
# ABOUTME: Manages sync loop, error handling, and state management

from pathlib import Path
from typing import Optional
import time
import structlog

from gchat_mirror.common.database import Database
from gchat_mirror.sync.auth import authenticate
from gchat_mirror.sync.google_client import GoogleChatClient
from gchat_mirror.sync.storage import SyncStorage

logger = structlog.get_logger()

class SyncDaemon:
    """Main sync daemon for Google Chat."""
    
    def __init__(self, data_dir: Path, config: dict):
        self.data_dir = Path(data_dir)
        self.config = config
        self.chat_db = Database(self.data_dir / "sync" / "chat.db")
        self.running = False
    
    def start(self):
        """Start the sync daemon."""
        logger.info("sync_daemon_starting")
        
        # Connect to database
        self.chat_db.connect()
        
        # Run integrity check
        if not self.chat_db.integrity_check():
            logger.error("database_integrity_check_failed")
            raise RuntimeError("Database integrity check failed")
        
        # Authenticate
        creds = authenticate(self.config.get("credential_key", "gchat-sync"))
        
        # Create API client
        self.client = GoogleChatClient(creds)
        self.storage = SyncStorage(self.chat_db.conn)
        
        # Run initial sync
        self.initial_sync()
        
        # Start poll loop (for Phase 1, just one iteration)
        logger.info("sync_daemon_started")
    
    def initial_sync(self):
        """Run initial sync for all spaces."""
        logger.info("initial_sync_starting")
        
        # Discover spaces
        spaces = self.client.list_spaces()
        logger.info("spaces_discovered", count=len(spaces))
        
        # Sync each space
        for space in spaces:
            self.sync_space(space)
        
        logger.info("initial_sync_complete")
    
    def sync_space(self, space: dict):
        """Sync a single space."""
        space_id = space["name"]
        logger.info("syncing_space", space_id=space_id)
        
        # Store space
        self.storage.upsert_space(space)
        
        # Fetch messages
        page_token = self.storage.get_space_sync_cursor(space_id)
        
        while True:
            response = self.client.list_messages(
                space_id, 
                page_token=page_token
            )
            
            messages = response.get("messages", [])
            for message in messages:
                self._process_message(message)
            
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        
        logger.info("space_synced", space_id=space_id, 
                   message_count=len(messages))
    
    def _process_message(self, message: dict):
        """Process and store a single message."""
        # Extract sender, store user if needed
        sender = message.get("sender", {})
        if sender:
            self.storage.upsert_user(sender)
        
        # Store message
        self.storage.insert_message(message)
    
    def stop(self):
        """Stop the sync daemon."""
        logger.info("sync_daemon_stopping")
        self.running = False
        if hasattr(self, 'client'):
            self.client.close()
        self.chat_db.close()
```

**Test**:

```python
def test_sync_daemon_initial_sync(tmp_path, httpx_mock):
    """Test initial sync process."""
    # Mock API responses
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces",
        json={
            "spaces": [
                {
                    "name": "spaces/TEST123",
                    "displayName": "Test Space",
                    "type": "SPACE"
                }
            ]
        }
    )
    
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces/TEST123/messages",
        json={
            "messages": [
                {
                    "name": "spaces/TEST123/messages/MSG1",
                    "text": "Hello world",
                    "createTime": "2025-01-01T10:00:00Z",
                    "sender": {
                        "name": "users/USER1",
                        "displayName": "Test User",
                        "type": "HUMAN"
                    }
                }
            ]
        }
    )
    
    # Setup
    config = {"credential_key": "test-key"}
    daemon = SyncDaemon(tmp_path, config)
    
    # Run migrations first
    from gchat_mirror.common.migrations import run_migrations
    run_migrations(
        tmp_path / "sync" / "chat.db",
        Path("migrations")
    )
    
    # Mock authentication
    mock_creds = Mock(token="test_token", valid=True)
    with patch('gchat_mirror.sync.auth.authenticate', return_value=mock_creds):
        daemon.start()
    
    # Verify space was stored
    cursor = daemon.chat_db.conn.execute(
        "SELECT display_name FROM spaces WHERE id = ?",
        ("spaces/TEST123",)
    )
    result = cursor.fetchone()
    assert result["display_name"] == "Test Space"
    
    # Verify message was stored
    cursor = daemon.chat_db.conn.execute(
        "SELECT text FROM messages WHERE id = ?",
        ("spaces/TEST123/messages/MSG1",)
    )
    result = cursor.fetchone()
    assert result["text"] == "Hello world"
    
    # Verify user was stored
    cursor = daemon.chat_db.conn.execute(
        "SELECT display_name FROM users WHERE id = ?",
        ("users/USER1",)
    )
    result = cursor.fetchone()
    assert result["display_name"] == "Test User"
```

### 5. CLI Interface

#### 5.1 Main CLI Entry Point

**Test**: CLI loads and shows help

**File**: `src/gchat_mirror/cli/main.py`

```python
# ABOUTME: Main CLI entry point using Click
# ABOUTME: Defines command groups and common options

import click
import structlog
from pathlib import Path

from gchat_mirror.cli import sync, export, clients

@click.group()
@click.option(
    '--data-dir',
    type=click.Path(path_type=Path),
    default=lambda: Path.home() / '.local' / 'share' / 'gchat-mirror',
    help='Data directory for databases'
)
@click.option(
    '--config-dir',
    type=click.Path(path_type=Path),
    default=lambda: Path.home() / '.config' / 'gchat-mirror',
    help='Configuration directory'
)
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx, data_dir: Path, config_dir: Path, debug: bool):
    """GChat Mirror - Mirror Google Chat to SQLite and export to destinations."""
    # Setup logging
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        )
    )
    
    # Store in context
    ctx.ensure_object(dict)
    ctx.obj['data_dir'] = data_dir
    ctx.obj['config_dir'] = config_dir
    ctx.obj['debug'] = debug

# Register command groups
cli.add_command(sync.sync)
cli.add_command(export.export)
cli.add_command(clients.clients)

if __name__ == '__main__':
    cli()
```

**Test**:

```python
def test_cli_help():
    """Test that CLI shows help."""
    from click.testing import CliRunner
    from gchat_mirror.cli.main import cli
    
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    
    assert result.exit_code == 0
    assert 'GChat Mirror' in result.output
    assert 'sync' in result.output
    assert 'export' in result.output
```

#### 5.2 Sync Commands

**Test**: Sync start command works

**File**: `src/gchat_mirror/cli/sync.py`

```python
# ABOUTME: CLI commands for sync daemon
# ABOUTME: Handles start, stop, status, and backfill commands

import click
import toml
from pathlib import Path
import structlog

from gchat_mirror.sync.daemon import SyncDaemon

logger = structlog.get_logger()

@click.group()
def sync():
    """Sync daemon commands."""
    pass

@sync.command()
@click.pass_context
def start(ctx):
    """Start the sync daemon."""
    data_dir = ctx.obj['data_dir']
    config_dir = ctx.obj['config_dir']
    
    # Load config
    config_file = config_dir / 'sync' / 'config.toml'
    if config_file.exists():
        config = toml.load(config_file)
    else:
        logger.warning("no_config_file", path=str(config_file))
        config = {}
    
    # Override with environment variables
    config = _apply_env_overrides(config)
    
    # Create and start daemon
    daemon = SyncDaemon(data_dir, config)
    
    try:
        daemon.start()
    except KeyboardInterrupt:
        logger.info("interrupt_received")
        daemon.stop()
    except Exception as e:
        logger.error("sync_daemon_error", error=str(e), exc_info=True)
        daemon.stop()
        raise

@sync.command()
@click.pass_context
def status(ctx):
    """Show sync daemon status."""
    data_dir = ctx.obj['data_dir']
    
    # Query health endpoint (Phase 3)
    # For Phase 1, just check if database exists
    db_path = data_dir / 'sync' / 'chat.db'
    if db_path.exists():
        click.echo(f"Database: {db_path}")
        click.echo(f"Size: {db_path.stat().st_size / 1024 / 1024:.2f} MB")
        
        # Show basic stats
        import sqlite3
        conn = sqlite3.connect(db_path)
        
        cursor = conn.execute("SELECT COUNT(*) FROM spaces")
        space_count = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        message_count = cursor.fetchone()[0]
        
        click.echo(f"Spaces: {space_count}")
        click.echo(f"Messages: {message_count}")
        
        conn.close()
    else:
        click.echo("No database found. Run 'gchat-mirror sync start' first.")

@sync.command()
@click.option('--space-id', help='Space ID to backfill')
@click.option('--days', type=int, default=365, help='Days of history to fetch')
@click.pass_context
def backfill(ctx, space_id: str, days: int):
    """Backfill historical messages."""
    # Placeholder for Phase 1, implement in Phase 3
    click.echo("Backfill command not yet implemented (Phase 3)")

def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides to config."""
    import os
    
    # Example: GCHAT_MIRROR_SYNC_POLL_INTERVAL
    # Maps to config['sync']['poll_interval']
    
    for key, value in os.environ.items():
        if not key.startswith('GCHAT_MIRROR_'):
            continue
        
        # Parse key: GCHAT_MIRROR_SECTION_KEY
        parts = key.replace('GCHAT_MIRROR_', '').lower().split('_', 1)
        if len(parts) == 2:
            section, option = parts
            if section not in config:
                config[section] = {}
            config[section][option] = value
    
    return config
```

**Test**:

```python
def test_sync_start_command(tmp_path, monkeypatch):
    """Test sync start command."""
    from click.testing import CliRunner
    from gchat_mirror.cli.main import cli
    
    # Setup
    monkeypatch.setenv('HOME', str(tmp_path))
    
    runner = CliRunner()
    
    # Mock daemon to avoid actual API calls
    mock_daemon = Mock()
    with patch('gchat_mirror.cli.sync.SyncDaemon', return_value=mock_daemon):
        result = runner.invoke(cli, [
            '--data-dir', str(tmp_path / 'data'),
            'sync', 'start'
        ])
    
    # Verify daemon was started
    mock_daemon.start.assert_called_once()

def test_sync_status_command(tmp_path):
    """Test sync status command."""
    from click.testing import CliRunner
    from gchat_mirror.cli.main import cli
    
    # Create test database
    db_path = tmp_path / 'data' / 'sync' / 'chat.db'
    db_path.parent.mkdir(parents=True)
    
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE spaces (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO spaces (id) VALUES ('space1')")
    conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    conn.commit()
    conn.close()
    
    runner = CliRunner()
    result = runner.invoke(cli, [
        '--data-dir', str(tmp_path / 'data'),
        'sync', 'status'
    ])
    
    assert result.exit_code == 0
    assert 'Spaces: 1' in result.output
    assert 'Messages: 1' in result.output
```

#### 5.3 Export Commands (Placeholder)

**Test**: Export commands exist but are not implemented

**File**: `src/gchat_mirror/cli/export.py`

```python
# ABOUTME: CLI commands for export clients
# ABOUTME: Handles starting and managing export clients (Phase 4)

import click

@click.group()
def export():
    """Export client commands."""
    pass

@export.group()
def discourse():
    """Discourse exporter commands."""
    pass

@discourse.command()
@click.pass_context
def start(ctx):
    """Start Discourse exporter."""
    click.echo("Discourse exporter not yet implemented (Phase 4)")

@discourse.command()
@click.pass_context
def status(ctx):
    """Show Discourse exporter status."""
    click.echo("Discourse exporter not yet implemented (Phase 4)")
```

#### 5.4 Client Management Commands (Placeholder)

**Test**: Client commands exist but are not implemented

**File**: `src/gchat_mirror/cli/clients.py`

```python
# ABOUTME: CLI commands for managing export clients
# ABOUTME: Lists and unregisters export clients (Phase 2+)

import click

@click.group()
def clients():
    """Export client management."""
    pass

@clients.command()
@click.pass_context
def list(ctx):
    """List registered export clients."""
    click.echo("Client management not yet implemented (Phase 2)")

@clients.command()
@click.argument('client_id')
@click.pass_context
def unregister(ctx, client_id: str):
    """Unregister an export client."""
    click.echo(f"Client management not yet implemented (Phase 2)")
```

### 6. Logging Setup

#### 6.1 Structured Logging Configuration

**Test**: Logging produces structured JSON output

**File**: `src/gchat_mirror/common/logging.py`

```python
# ABOUTME: Structured logging configuration using structlog
# ABOUTME: Sets up JSON logging with systemd integration

import logging
import sys
import structlog
from typing import Any

def configure_logging(debug: bool = False):
    """Configure structured logging with structlog."""
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if debug else logging.INFO,
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str = None) -> Any:
    """Get a structlog logger."""
    return structlog.get_logger(name)
```

**Test**:

```python
def test_structured_logging():
    """Test that logging produces JSON output."""
    import io
    from gchat_mirror.common.logging import configure_logging, get_logger
    
    # Capture output
    output = io.StringIO()
    
    # Configure logging to output stream
    import sys
    old_stdout = sys.stdout
    sys.stdout = output
    
    configure_logging(debug=True)
    logger = get_logger("test")
    
    logger.info("test_message", key="value", count=42)
    
    sys.stdout = old_stdout
    
    # Parse output as JSON
    import json
    log_line = output.getvalue().strip()
    log_data = json.loads(log_line)
    
    assert log_data["event"] == "test_message"
    assert log_data["key"] == "value"
    assert log_data["count"] == 42
    assert "timestamp" in log_data
    assert log_data["level"] == "info"
```

### 7. Configuration Management

#### 7.1 Config File Loading

**Test**: Can load TOML config and apply environment overrides

**File**: `src/gchat_mirror/common/config.py`

```python
# ABOUTME: Configuration loading and management
# ABOUTME: Handles TOML files and environment variable overrides

import os
import toml
from pathlib import Path
from typing import Dict, Any
import structlog

logger = structlog.get_logger()

def load_config(config_path: Path, defaults: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Load configuration from TOML file with environment overrides.
    
    Args:
        config_path: Path to TOML config file
        defaults: Default configuration values
    
    Returns:
        Merged configuration dictionary
    """
    config = defaults.copy() if defaults else {}
    
    # Load from file if exists
    if config_path.exists():
        file_config = toml.load(config_path)
        config = _deep_merge(config, file_config)
        logger.info("config_loaded", path=str(config_path))
    else:
        logger.warning("config_file_not_found", path=str(config_path))
    
    # Apply environment variable overrides
    config = apply_env_overrides(config)
    
    return config

def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result

def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to config."""
    # Look for GCHAT_MIRROR_* environment variables
    # Format: GCHAT_MIRROR_SECTION_KEY=value
    
    for key, value in os.environ.items():
        if not key.startswith('GCHAT_MIRROR_'):
            continue
        
        # Parse the key
        parts = key.replace('GCHAT_MIRROR_', '').lower().split('_')
        
        # Navigate to the right place in config
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        # Set the value (try to parse as int/bool if possible)
        final_key = parts[-1]
        current[final_key] = _parse_value(value)
    
    return config

def _parse_value(value: str) -> Any:
    """Parse string value to appropriate type."""
    # Try boolean
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    
    # Try integer
    try:
        return int(value)
    except ValueError:
        pass
    
    # Return as string
    return value

def get_default_sync_config() -> Dict[str, Any]:
    """Get default configuration for sync daemon."""
    return {
        'auth': {
            'credential_key': 'gchat-sync'
        },
        'sync': {
            'initial_sync_days': 90,
            'active_space_poll_seconds': 10,
            'quiet_space_poll_minutes': 5,
            'download_workers': None,  # Will default to CPU/2
        },
        'monitoring': {
            'health_check_port': 4981
        }
    }
```

**Test**:

```python
def test_load_config_from_file(tmp_path):
    """Test loading configuration from TOML file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[auth]
credential_key = "test-key"

[sync]
initial_sync_days = 30
    """)
    
    config = load_config(config_file)
    
    assert config['auth']['credential_key'] == "test-key"
    assert config['sync']['initial_sync_days'] == 30

def test_env_override(tmp_path, monkeypatch):
    """Test environment variable overrides."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[sync]
initial_sync_days = 90
    """)
    
    monkeypatch.setenv('GCHAT_MIRROR_SYNC_INITIAL_SYNC_DAYS', '30')
    
    config = load_config(config_file)
    
    assert config['sync']['initial_sync_days'] == 30

def test_deep_merge():
    """Test deep merging of configurations."""
    base = {
        'a': {'b': 1, 'c': 2},
        'd': 3
    }
    override = {
        'a': {'b': 10},
        'e': 4
    }
    
    result = _deep_merge(base, override)
    
    assert result['a']['b'] == 10  # Overridden
    assert result['a']['c'] == 2   # Preserved
    assert result['d'] == 3        # Preserved
    assert result['e'] == 4        # Added
```

### 8. Integration Tests

#### 8.1 End-to-End Sync Test

**Test**: Full sync process with mocked API

**File**: `tests/test_sync/test_integration.py`

```python
# ABOUTME: Integration tests for sync daemon
# ABOUTME: Tests complete sync flow with mocked Google Chat API

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
import sqlite3

from gchat_mirror.sync.daemon import SyncDaemon
from gchat_mirror.common.migrations import run_migrations

@pytest.fixture
def test_data_dir(tmp_path):
    """Create test data directory with database."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Run migrations
    db_path = data_dir / "sync" / "chat.db"
    db_path.parent.mkdir(parents=True)
    run_migrations(db_path, Path("migrations"))
    
    return data_dir

@pytest.fixture
def mock_google_responses():
    """Fixture providing mock Google Chat API responses."""
    return {
        'spaces': {
            "spaces": [
                {
                    "name": "spaces/AAAA1234",
                    "displayName": "Engineering",
                    "type": "SPACE",
                    "spaceThreadingState": "THREADED_MESSAGES"
                },
                {
                    "name": "spaces/BBBB5678",
                    "displayName": "Design",
                    "type": "SPACE",
                    "spaceThreadingState": "THREADED_MESSAGES"
                }
            ]
        },
        'messages_AAAA1234': {
            "messages": [
                {
                    "name": "spaces/AAAA1234/messages/MSG001",
                    "text": "Hello everyone!",
                    "createTime": "2025-01-15T10:00:00Z",
                    "sender": {
                        "name": "users/USER001",
                        "displayName": "Alice",
                        "type": "HUMAN",
                        "email": "alice@example.com"
                    },
                    "thread": {
                        "name": "spaces/AAAA1234/threads/THREAD001"
                    }
                },
                {
                    "name": "spaces/AAAA1234/messages/MSG002",
                    "text": "Hi Alice!",
                    "createTime": "2025-01-15T10:05:00Z",
                    "sender": {
                        "name": "users/USER002",
                        "displayName": "Bob",
                        "type": "HUMAN",
                        "email": "bob@example.com"
                    },
                    "thread": {
                        "name": "spaces/AAAA1234/threads/THREAD001"
                    }
                }
            ]
        },
        'messages_BBBB5678': {
            "messages": [
                {
                    "name": "spaces/BBBB5678/messages/MSG003",
                    "text": "Design review today",
                    "createTime": "2025-01-15T11:00:00Z",
                    "sender": {
                        "name": "users/USER001",
                        "displayName": "Alice",
                        "type": "HUMAN",
                        "email": "alice@example.com"
                    }
                }
            ]
        }
    }

def test_full_sync_process(test_data_dir, mock_google_responses, httpx_mock):
    """Test complete sync process from API to database."""
    
    # Mock API endpoints
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces",
        json=mock_google_responses['spaces']
    )
    
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces/AAAA1234/messages",
        json=mock_google_responses['messages_AAAA1234']
    )
    
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/spaces/BBBB5678/messages",
        json=mock_google_responses['messages_BBBB5678']
    )
    
    # Create daemon
    config = {'credential_key': 'test-key'}
    daemon = SyncDaemon(test_data_dir, config)
    
    # Mock authentication
    mock_creds = Mock(token="test_token", valid=True, expired=False)
    with patch('gchat_mirror.sync.auth.authenticate', return_value=mock_creds):
        daemon.start()
    
    # Verify database contents
    db_path = test_data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Check spaces
    cursor = conn.execute("SELECT * FROM spaces ORDER BY id")
    spaces = cursor.fetchall()
    assert len(spaces) == 2
    assert spaces[0]['id'] == 'spaces/AAAA1234'
    assert spaces[0]['display_name'] == 'Engineering'
    assert spaces[1]['id'] == 'spaces/BBBB5678'
    
    # Check users
    cursor = conn.execute("SELECT * FROM users ORDER BY id")
    users = cursor.fetchall()
    assert len(users) == 2
    assert users[0]['display_name'] == 'Alice'
    assert users[1]['display_name'] == 'Bob'
    
    # Check messages
    cursor = conn.execute("SELECT * FROM messages ORDER BY create_time")
    messages = cursor.fetchall()
    assert len(messages) == 3
    assert messages[0]['text'] == 'Hello everyone!'
    assert messages[0]['sender_id'] == 'users/USER001'
    assert messages[0]['thread_id'] == 'spaces/AAAA1234/threads/THREAD001'
    assert messages[1]['text'] == 'Hi Alice!'
    assert messages[2]['text'] == 'Design review today'
    
    conn.close()
    daemon.stop()
```

### 9. Documentation

#### 9.1 README

**File**: `README.md`

Contents are between the horizontal lines, for easy demarcation. 

---
# GChat Mirror

Mirror Google Chat data to local SQLite databases and export to various destinations (starting with Discourse).

## Features (Phase 1)

- Authenticate with Google Chat via OAuth
- Mirror spaces, messages, and users to local SQLite database
- Sequential polling of all accessible spaces
- Basic CLI interface
- Structured JSON logging

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/gchat-mirror.git
cd gchat-mirror

# Install with uv
uv sync

# Install in development mode
uv pip install -e ".[dev]"
```

## Setup

1. Create a Google Cloud project and enable the Google Chat API
1. Create OAuth 2.0 credentials (Desktop application)
1. Download credentials as `client_secrets.json`
1. Run initial sync:

```bash
gchat-mirror sync start
```

This will:

- Prompt for OAuth authentication (browser will open)
- Store credentials in system keychain
- Sync last 90 days of history from all spaces
- Store data in `~/.local/share/gchat-mirror/sync/`

## Usage

```bash
# Start sync daemon
gchat-mirror sync start

# Check sync status
gchat-mirror sync status

# View help
gchat-mirror --help
```

## Configuration

Create `~/.config/gchat-mirror/sync/config.toml`:

```toml
[auth]
credential_key = "gchat-sync"

[sync]
initial_sync_days = 90

[monitoring]
health_check_port = 4981
```

Environment variables override config:

```bash
export GCHAT_MIRROR_SYNC_INITIAL_SYNC_DAYS=30
gchat-mirror sync start
```

## Development

```bash
# Run tests
uv run pytest

# Run with debug logging
gchat-mirror --debug sync start

# Format code
uv run black src/ tests/
uv run ruff check src/ tests/
```
---

## Project Structure

- `src/gchat_mirror/sync/` - Sync daemon
- `src/gchat_mirror/common/` - Shared utilities
- `src/gchat_mirror/cli/` - CLI interface
- `migrations/` - Database migrations
- `tests/` - Test suite

## License

GPL-3


### 10. Phase 1 Completion Checklist

**Before marking Phase 1 complete, verify:**

- [ ] Project setup complete (uv, pyproject.toml, directory structure)
- [ ] Database schema created and migrations work
- [ ] Can authenticate with Google Chat OAuth
- [ ] Can fetch spaces from Google Chat API
- [ ] Can fetch messages from spaces
- [ ] Messages, users, and spaces stored in database
- [ ] CLI `sync start` command works
- [ ] CLI `sync status` command shows database stats
- [ ] Structured logging produces JSON output
- [ ] Configuration loads from TOML and environment variables
- [ ] Unit tests pass for all components
- [ ] Integration test passes (full sync with mocked API)
- [ ] README documentation complete
- [ ] Code follows TDD approach (tests written first)
- [ ] All code has ABOUTME comments
- [ ] Git repository initialized with proper .gitignore

## Success Criteria

Phase 1 is complete when:

1. **Authentication works**: Can obtain and store Google OAuth credentials
2. **API client works**: Can fetch spaces and messages from Google Chat
3. **Database works**: Data is stored correctly with proper schema
4. **CLI works**: Can start sync and view status
5. **Tests pass**: All unit and integration tests pass
6. **Logging works**: Structured JSON logs are produced
7. **Config works**: Can load from file and override with environment
8. **Documentation exists**: README explains setup and usage

## Next Phase

After Phase 1 completion, proceed to Phase 2: Complete Data Model, which will add:
- Attachment storage and downloading
- User avatars with history
- Reactions and custom emoji
- Message revisions
- Read receipts
- Notification queue
- Export client registration
