# Phase 2 Part 1: Attachments Database

## Overview

Set up the attachments database with schema for storing binary data using inline and chunked storage strategies.

## Tasks

### 1.1 Create attachments.db Schema

**Test**: Migration creates attachments.db with proper schema

**File**: `migrations/002_initial_attachments.py`

```python
# ABOUTME: Initial schema for attachments database
# ABOUTME: Creates tables for inline and chunked attachment storage

def upgrade(conn):
    """Create attachments.db schema."""
    
    # Small files stored whole
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attachment_inline (
            attachment_id TEXT PRIMARY KEY,
            data BLOB NOT NULL,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Large files stored in chunks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attachment_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attachment_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            
            data BLOB NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256_hash TEXT,
            
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(attachment_id, chunk_index)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_attachment 
        ON attachment_chunks(attachment_id, chunk_index)
    """)
    
    # Storage metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS storage_metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Storage stats tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS storage_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            total_attachments INTEGER,
            inline_count INTEGER,
            chunked_count INTEGER,
            total_size_bytes INTEGER,
            db_size_bytes INTEGER
        )
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS attachment_inline")
    conn.execute("DROP TABLE IF EXISTS attachment_chunks")
    conn.execute("DROP TABLE IF EXISTS storage_metadata")
    conn.execute("DROP TABLE IF EXISTS storage_stats")
    conn.commit()
```

**Test**:

```python
def test_attachments_db_migration(tmp_path):
    """Test attachments.db schema creation."""
    from migrations.002_initial_attachments import upgrade
    
    db_path = tmp_path / "attachments.db"
    conn = sqlite3.connect(db_path)
    
    upgrade(conn)
    
    # Verify tables exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    
    assert 'attachment_inline' in tables
    assert 'attachment_chunks' in tables
    assert 'storage_metadata' in tables
    assert 'storage_stats' in tables
    
    conn.close()
```

### 1.2 Add Attachments Table to chat.db

**Test**: Migration adds attachments metadata table

**File**: `migrations/003_add_attachments.py`

```python
# ABOUTME: Add attachments metadata table to chat.db
# ABOUTME: Stores attachment metadata with download tracking

def upgrade(conn):
    """Add attachments table to chat.db."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            
            name TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            
            source_url TEXT,
            thumbnail_url TEXT,
            
            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,
            
            storage_type TEXT DEFAULT 'chunked',
            chunk_size INTEGER,
            total_chunks INTEGER,
            
            sha256_hash TEXT,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attachments_message 
        ON attachments(message_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attachments_downloaded 
        ON attachments(downloaded)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attachments_hash 
        ON attachments(sha256_hash)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_attachments_download_pending 
        ON attachments(downloaded, download_attempts)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS attachments")
    conn.commit()
```

**Test**:

```python
def test_attachments_metadata_table(tmp_path):
    """Test attachments metadata table creation."""
    from migrations.003_add_attachments import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create messages table first (dependency)
    conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            text TEXT
        )
    """)
    
    upgrade(conn)
    
    # Insert test attachment
    conn.execute("""
        INSERT INTO messages (id, text) VALUES ('msg1', 'test')
    """)
    
    conn.execute("""
        INSERT INTO attachments (id, message_id, name, size_bytes)
        VALUES ('att1', 'msg1', 'test.pdf', 1024)
    """)
    
    # Verify
    cursor = conn.execute("SELECT name, size_bytes FROM attachments WHERE id = ?", ('att1',))
    row = cursor.fetchone()
    assert row[0] == 'test.pdf'
    assert row[1] == 1024
    
    conn.close()
```

## Completion Criteria

- [ ] attachments.db schema created with all tables
- [ ] attachments metadata table added to chat.db
- [ ] All indexes created properly
- [ ] Foreign keys work correctly
- [ ] Tests pass for both migrations
