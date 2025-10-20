# Phase 4.1: Exporter Database Schema

## Goal

Create the database schema for tracking Discourse export state, mappings, and failures.

## Duration

1 day

## Prerequisites

- Phase 1, 2, and 3 complete
- Discourse instance available with admin API key
- All data types stored in chat.db

## Overview

The exporter maintains its own state database (separate from chat.db) to track:

1. **Export Mappings** - Google Chat ID → Discourse ID
2. **Failed Exports** - Exports that need retry with exponential backoff
3. **Export Progress** - Per-space progress tracking
4. **Exporter State** - Configuration and global state

## Tasks

### 1. Create Exporter State Database

#### 1.1 Database Schema Migration

**Test**: Migration creates exporter state tables

**File**: `migrations/discourse/001_initial_state.py`

```python
# ABOUTME: Initial schema for Discourse exporter state tracking
# ABOUTME: Tracks export status, mappings, and failed operations

def upgrade(conn):
    """Create Discourse exporter state tables."""
    
    # Export mapping: Google Chat → Discourse
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            
            discourse_type TEXT NOT NULL,
            discourse_id INTEGER NOT NULL,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(source_type, source_id)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mappings_source
        ON export_mappings(source_type, source_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mappings_discourse
        ON export_mappings(discourse_type, discourse_id)
    """)
    
    # Failed exports for retry
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            
            error_message TEXT,
            error_count INTEGER DEFAULT 1,
            
            blocked_by TEXT,
            
            first_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            next_retry TIMESTAMP,
            
            UNIQUE(entity_type, entity_id, operation)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_failed_retry
        ON failed_exports(next_retry)
    """)
    
    # Export progress tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            space_id TEXT NOT NULL UNIQUE,
            
            threads_exported INTEGER DEFAULT 0,
            messages_exported INTEGER DEFAULT 0,
            attachments_exported INTEGER DEFAULT 0,
            reactions_exported INTEGER DEFAULT 0,
            
            last_exported_message_time TIMESTAMP,
            
            status TEXT DEFAULT 'pending',
            
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Configuration and state
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exporter_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Set initial state
    conn.execute("""
        INSERT INTO exporter_state (key, value)
        VALUES ('mapping_mode', 'hybrid')
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS export_mappings")
    conn.execute("DROP TABLE IF EXISTS failed_exports")
    conn.execute("DROP TABLE IF EXISTS export_progress")
    conn.execute("DROP TABLE IF EXISTS exporter_state")
    conn.commit()
```

**Test**:

```python
def test_discourse_exporter_schema(tmp_path):
    """Test exporter state database schema."""
    from migrations.discourse.001_initial_state import upgrade
    
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)
    
    upgrade(conn)
    
    # Verify tables exist
    cursor = conn.execute("""
        SELECT name FROM sqlite_master WHERE type='table'
    """)
    tables = {row[0] for row in cursor.fetchall()}
    
    assert 'export_mappings' in tables
    assert 'failed_exports' in tables
    assert 'export_progress' in tables
    assert 'exporter_state' in tables
    
    # Verify initial state
    cursor = conn.execute("""
        SELECT value FROM exporter_state WHERE key = 'mapping_mode'
    """)
    assert cursor.fetchone()[0] == 'hybrid'
    
    conn.close()
```

### 2. Migration Runner Integration

#### 2.1 Integrate with Migration System

**Test**: Exporter migrations run automatically

**File**: `src/gchat_mirror/common/migrations.py` (additions)

```python
# Add support for discourse migrations directory

def get_discourse_migrations_dir() -> Path:
    """Get path to discourse migrations directory."""
    return Path(__file__).parent.parent.parent.parent / "migrations" / "discourse"

def run_discourse_migrations(conn: sqlite3.Connection):
    """
    Run discourse exporter migrations.
    
    Args:
        conn: Connection to exporter state database
    """
    migrations_dir = get_discourse_migrations_dir()
    
    if not migrations_dir.exists():
        logger.info("no_discourse_migrations_found")
        return
    
    # Create migrations table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    # Get applied migrations
    cursor = conn.execute("SELECT version FROM schema_migrations")
    applied = {row[0] for row in cursor.fetchall()}
    
    # Find migration files
    migration_files = sorted(migrations_dir.glob("*.py"))
    
    for migration_file in migration_files:
        version = migration_file.stem
        
        if version in applied or version.startswith("_"):
            continue
        
        logger.info("running_discourse_migration", version=version)
        
        # Load and run migration
        spec = importlib.util.spec_from_file_location(version, migration_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Run upgrade
        module.upgrade(conn)
        
        # Record migration
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (version,)
        )
        conn.commit()
        
        logger.info("discourse_migration_complete", version=version)
```

**Test**:

```python
def test_run_discourse_migrations(tmp_path):
    """Test running discourse migrations."""
    from gchat_mirror.common.migrations import run_discourse_migrations
    
    state_db = tmp_path / "state.db"
    conn = sqlite3.connect(state_db)
    
    run_discourse_migrations(conn)
    
    # Verify migrations table exists
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='schema_migrations'
    """)
    assert cursor.fetchone() is not None
    
    # Verify migration was applied
    cursor = conn.execute("""
        SELECT version FROM schema_migrations
    """)
    versions = [row[0] for row in cursor.fetchall()]
    assert '001_initial_state' in versions
    
    conn.close()
```

## Schema Details

### export_mappings Table

Maps Google Chat entities to their Discourse counterparts:

- **source_type**: 'space', 'thread', 'message', 'user', 'attachment', 'reaction'
- **source_id**: Google Chat entity ID
- **discourse_type**: 'category', 'chat_channel', 'topic', 'private_message', 'post', 'user', 'attachment', 'reaction'
- **discourse_id**: Discourse entity ID (or URL for attachments)

Examples:
- Space → Category: `('space', 'spaces/abc123', 'category', 42)`
- Thread → Topic: `('thread', 'spaces/abc123/threads/xyz789', 'topic', 156)`
- Message → Post: `('message', 'spaces/abc123/messages/msg456', 'post', 789)`
- User → User: `('user', 'users/user123', 'user', 'alice_smith')`

### failed_exports Table

Tracks failed exports for retry with exponential backoff:

- **entity_type**: Type of entity that failed
- **entity_id**: Entity ID
- **operation**: 'export', 'update', etc.
- **error_message**: Error details
- **error_count**: Number of failed attempts
- **blocked_by**: Entity ID that blocks this (for dependency tracking)
- **next_retry**: When to retry next

### export_progress Table

Tracks export progress per space:

- **space_id**: Google Chat space ID
- **threads_exported**: Count of exported threads
- **messages_exported**: Count of exported messages
- **attachments_exported**: Count of exported attachments
- **reactions_exported**: Count of exported reactions
- **status**: 'pending', 'in_progress', 'completed', 'failed'
- **started_at**, **completed_at**: Timestamps

### exporter_state Table

Key-value store for exporter configuration:

- **mapping_mode**: 'chat', 'private_messages', or 'hybrid'
- **last_notification_id**: Last processed notification (for incremental export)

## Completion Criteria

- [ ] Migration creates all required tables
- [ ] Indexes created for performance
- [ ] Migration system integrated
- [ ] All tests pass
- [ ] Schema documented

## Next Steps

After Phase 4.1, proceed to Phase 4.2: Discourse API Client
