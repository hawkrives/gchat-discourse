# Phase 2 Part 4: Advanced Data Types & Notification System

## Overview

Complete the Phase 2 data model with user avatars, reactions, custom emoji, message revisions, read receipts, notification queue, and export client registration.

## Duration

1-2 weeks

## Prerequisites

- Phase 1 complete (basic sync working)
- Phase 2 Parts 1-3 complete (attachments working)

## Tasks

### 1. User Avatars with History

#### 1.1 Add Avatar Tables

**Test**: Migration creates avatar tables and indexes

**File**: `migrations/004_user_avatars.py`

```python
# ABOUTME: Add avatar tracking tables with history
# ABOUTME: Stores avatar URLs and downloaded data with change tracking

def upgrade(conn):
    """Add user avatar tables."""
    
    # Avatar metadata in chat.db
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_avatars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            avatar_url TEXT NOT NULL,
            
            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,
            
            storage_id TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_current BOOLEAN DEFAULT TRUE,
            
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_avatars_user 
        ON user_avatars(user_id, is_current)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_avatars_download
        ON user_avatars(downloaded, download_attempts)
    """)
    
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_avatars_unique
        ON user_avatars(user_id, avatar_url) 
        WHERE is_current = TRUE
    """)
    
    # Add avatar_id column to users table
    conn.execute("""
        ALTER TABLE users 
        ADD COLUMN current_avatar_id INTEGER 
        REFERENCES user_avatars(id)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    # SQLite doesn't support DROP COLUMN, would need to recreate table
    conn.execute("DROP TABLE IF EXISTS user_avatars")
    conn.commit()
```

**Test**:

```python
def test_user_avatars_migration(tmp_path):
    """Test user avatars table creation."""
    from migrations.004_user_avatars import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create users table first
    conn.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            display_name TEXT
        )
    """)
    conn.commit()
    
    upgrade(conn)
    
    # Verify table exists
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_avatars'
    """)
    assert cursor.fetchone() is not None
    
    # Test inserting avatar
    conn.execute("INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')")
    conn.execute("""
        INSERT INTO user_avatars (user_id, avatar_url, is_current)
        VALUES ('user1', 'https://example.com/avatar.jpg', TRUE)
    """)
    
    # Verify foreign key works
    cursor = conn.execute("""
        SELECT avatar_url FROM user_avatars WHERE user_id = ?
    """, ('user1',))
    assert cursor.fetchone()[0] == 'https://example.com/avatar.jpg'
    
    conn.close()
```

#### 1.2 Avatar Downloader

**Test**: Can download and track avatar changes

**File**: `src/gchat_mirror/sync/avatar_downloader.py`

```python
# ABOUTME: Avatar download management with history tracking
# ABOUTME: Handles downloading user avatars and tracking URL changes

import asyncio
import httpx
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog

from gchat_mirror.sync.attachment_storage import AttachmentStorage

logger = structlog.get_logger()

class AvatarDownloader:
    """Download and track user avatars."""
    
    def __init__(self, storage: AttachmentStorage, chat_conn):
        self.storage = storage
        self.chat_conn = chat_conn
    
    def update_user_avatar(self, user_id: str, avatar_url: Optional[str]):
        """
        Update user's avatar URL, creating history entry if changed.
        
        Args:
            user_id: User ID
            avatar_url: New avatar URL (or None if no avatar)
        """
        if not avatar_url:
            return
        
        # Check if this URL is already current
        cursor = self.chat_conn.execute("""
            SELECT id FROM user_avatars 
            WHERE user_id = ? AND avatar_url = ? AND is_current = TRUE
        """, (user_id, avatar_url))
        
        if cursor.fetchone():
            # URL unchanged, just update last_seen
            self.chat_conn.execute("""
                UPDATE user_avatars 
                SET last_seen = CURRENT_TIMESTAMP
                WHERE user_id = ? AND avatar_url = ? AND is_current = TRUE
            """, (user_id, avatar_url))
            self.chat_conn.commit()
            return
        
        # Mark old avatars as not current
        self.chat_conn.execute("""
            UPDATE user_avatars 
            SET is_current = FALSE
            WHERE user_id = ? AND is_current = TRUE
        """, (user_id,))
        
        # Insert new avatar record
        self.chat_conn.execute("""
            INSERT INTO user_avatars 
            (user_id, avatar_url, is_current)
            VALUES (?, ?, TRUE)
        """, (user_id, avatar_url))
        
        self.chat_conn.commit()
        
        logger.info("avatar_updated", user_id=user_id, url=avatar_url)
    
    async def download_pending_avatars(self, batch_size: int = 50):
        """Download pending avatars."""
        pending = self._get_pending_avatars(batch_size)
        
        if not pending:
            logger.info("no_pending_avatars")
            return
        
        logger.info("downloading_avatars", count=len(pending))
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True
        ) as session:
            tasks = [
                self._download_avatar(session, avatar)
                for avatar in pending
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success = sum(1 for r in results if r is True)
            failed = sum(1 for r in results if r is not True)
            
            logger.info("avatar_download_complete", 
                       success=success, failed=failed)
    
    def _get_pending_avatars(self, limit: int) -> List[Dict[str, Any]]:
        """Get pending avatar downloads."""
        cursor = self.chat_conn.execute("""
            SELECT id, user_id, avatar_url, download_attempts
            FROM user_avatars
            WHERE downloaded = FALSE
              AND download_attempts < 5
              AND is_current = TRUE
            ORDER BY first_seen DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    async def _download_avatar(self, session: httpx.AsyncClient, 
                               avatar: Dict[str, Any]) -> bool:
        """Download a single avatar."""
        try:
            response = await session.get(avatar['avatar_url'])
            
            if response.status_code != 200:
                logger.error("avatar_download_failed",
                           status=response.status_code,
                           user_id=avatar['user_id'])
                self._mark_download_failed(avatar['id'], 
                                          f"HTTP {response.status_code}")
                return False
            
            data = response.content
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            sha256 = hashlib.sha256(data).hexdigest()
            
            # Store in attachments.db using inline storage
            # (avatars are typically small)
            storage_id = f"avatar_{avatar['user_id']}_{avatar['id']}"
            
            self.storage.attachments_conn.execute("""
                INSERT INTO attachment_inline (attachment_id, data)
                VALUES (?, ?)
            """, (storage_id, data))
            
            # Update avatar record
            self.chat_conn.execute("""
                UPDATE user_avatars
                SET downloaded = TRUE,
                    download_time = CURRENT_TIMESTAMP,
                    storage_id = ?,
                    content_type = ?,
                    size_bytes = ?,
                    sha256_hash = ?
                WHERE id = ?
            """, (storage_id, content_type, len(data), sha256, avatar['id']))
            
            self.storage.attachments_conn.commit()
            self.chat_conn.commit()
            
            logger.info("avatar_downloaded", 
                       user_id=avatar['user_id'],
                       size_kb=len(data) / 1024)
            
            return True
        
        except Exception as e:
            logger.error("avatar_download_error",
                        user_id=avatar['user_id'],
                        error=str(e))
            self._mark_download_failed(avatar['id'], str(e))
            return False
    
    def _mark_download_failed(self, avatar_id: int, error: str):
        """Mark avatar download as failed."""
        self.chat_conn.execute("""
            UPDATE user_avatars
            SET download_error = ?,
                download_attempts = download_attempts + 1
            WHERE id = ?
        """, (error, avatar_id))
        self.chat_conn.commit()
```

**Test**:

```python
@pytest.mark.asyncio
async def test_avatar_download(tmp_path, httpx_mock):
    """Test avatar downloading."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    downloader = AvatarDownloader(storage, chat_db.conn)
    
    # Create user and avatar
    chat_db.conn.execute("""
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
    """)
    chat_db.conn.execute("""
        INSERT INTO user_avatars (user_id, avatar_url, is_current)
        VALUES ('user1', 'https://example.com/avatar.jpg', TRUE)
    """)
    chat_db.conn.commit()
    
    # Mock download
    avatar_data = b'\xff\xd8\xff\xe0' + b'\x00' * 100  # JPEG header + data
    httpx_mock.add_response(
        url='https://example.com/avatar.jpg',
        content=avatar_data,
        headers={'Content-Type': 'image/jpeg'}
    )
    
    # Download
    await downloader.download_pending_avatars()
    
    # Verify downloaded
    cursor = chat_db.conn.execute("""
        SELECT downloaded, size_bytes FROM user_avatars 
        WHERE user_id = 'user1'
    """)
    row = cursor.fetchone()
    assert row['downloaded'] == 1
    assert row['size_bytes'] == len(avatar_data)

def test_avatar_url_change_tracking(tmp_path):
    """Test that avatar URL changes create history entries."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    downloader = AvatarDownloader(storage, chat_db.conn)
    
    chat_db.conn.execute("""
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
    """)
    chat_db.conn.commit()
    
    # Set initial avatar
    downloader.update_user_avatar('user1', 'https://example.com/avatar1.jpg')
    
    # Change avatar
    downloader.update_user_avatar('user1', 'https://example.com/avatar2.jpg')
    
    # Verify history
    cursor = chat_db.conn.execute("""
        SELECT avatar_url, is_current 
        FROM user_avatars 
        WHERE user_id = 'user1'
        ORDER BY first_seen
    """)
    rows = cursor.fetchall()
    
    assert len(rows) == 2
    assert rows[0]['avatar_url'] == 'https://example.com/avatar1.jpg'
    assert rows[0]['is_current'] == 0  # No longer current
    assert rows[1]['avatar_url'] == 'https://example.com/avatar2.jpg'
    assert rows[1]['is_current'] == 1  # Current
```

### 2. Reactions and Custom Emoji

#### 2.1 Add Reactions Table

**Test**: Migration creates reactions table

**File**: `migrations/005_reactions.py`

```python
# ABOUTME: Add reactions table for message reactions
# ABOUTME: Stores emoji reactions with user attribution and timestamps

def upgrade(conn):
    """Add reactions table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            
            emoji_content TEXT NOT NULL,
            emoji_unicode TEXT,
            emoji_custom_id TEXT,
            
            user_id TEXT NOT NULL,
            create_time TIMESTAMP NOT NULL,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id),
            
            UNIQUE(message_id, emoji_content, user_id)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reactions_message 
        ON reactions(message_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reactions_user 
        ON reactions(user_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reactions_emoji
        ON reactions(emoji_custom_id)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS reactions")
    conn.commit()
```

**Test**:

```python
def test_reactions_migration(tmp_path):
    """Test reactions table creation."""
    from migrations.005_reactions import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create prerequisite tables
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    
    upgrade(conn)
    
    # Insert test reaction
    conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    conn.execute("INSERT INTO users (id) VALUES ('user1')")
    conn.execute("""
        INSERT INTO reactions 
        (id, message_id, emoji_content, user_id, create_time)
        VALUES ('react1', 'msg1', '👍', 'user1', '2025-01-15T10:00:00Z')
    """)
    
    # Verify unique constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO reactions 
            (id, message_id, emoji_content, user_id, create_time)
            VALUES ('react2', 'msg1', '👍', 'user1', '2025-01-15T10:01:00Z')
        """)
    
    conn.close()
```

#### 2.2 Add Custom Emoji Table

**Test**: Migration creates custom emoji table

**File**: `migrations/006_custom_emoji.py`

```python
# ABOUTME: Add custom emoji table for workspace custom emoji
# ABOUTME: Stores custom emoji metadata and download tracking

def upgrade(conn):
    """Add custom emoji table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_emoji (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            
            source_url TEXT,
            
            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,
            
            storage_id TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_custom_emoji_name 
        ON custom_emoji(name)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_custom_emoji_download
        ON custom_emoji(downloaded, download_attempts)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS custom_emoji")
    conn.commit()
```

**Test**:

```python
def test_custom_emoji_migration(tmp_path):
    """Test custom emoji table creation."""
    from migrations.006_custom_emoji import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    upgrade(conn)
    
    # Insert test emoji
    conn.execute("""
        INSERT INTO custom_emoji (id, name, source_url)
        VALUES ('emoji1', 'partyparrot', 'https://example.com/parrot.gif')
    """)
    
    cursor = conn.execute("""
        SELECT name FROM custom_emoji WHERE id = 'emoji1'
    """)
    assert cursor.fetchone()[0] == 'partyparrot'
    
    conn.close()
```

#### 2.3 Reaction Storage

**Test**: Can store and retrieve reactions

**File**: Update `src/gchat_mirror/sync/storage.py`

```python
# Add to SyncStorage class:

def upsert_reaction(self, reaction_data: Dict[str, Any]):
    """Insert or update a reaction."""
    self.conn.execute("""
        INSERT INTO reactions 
        (id, message_id, emoji_content, emoji_unicode, emoji_custom_id,
         user_id, create_time, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            emoji_content = excluded.emoji_content,
            updated_at = CURRENT_TIMESTAMP
    """, (
        reaction_data['name'],
        reaction_data['message_id'],
        reaction_data['emoji']['content'],
        reaction_data['emoji'].get('unicode'),
        reaction_data['emoji'].get('customEmoji', {}).get('uid'),
        reaction_data['user']['name'],
        reaction_data['createTime'],
        json.dumps(reaction_data)
    ))
    self.conn.commit()

def delete_reaction(self, reaction_id: str):
    """Delete a reaction (for when users remove reactions)."""
    self.conn.execute("""
        DELETE FROM reactions WHERE id = ?
    """, (reaction_id,))
    self.conn.commit()

def upsert_custom_emoji(self, emoji_data: Dict[str, Any]):
    """Insert or update custom emoji metadata."""
    emoji_id = emoji_data['customEmoji']['uid']
    
    self.conn.execute("""
        INSERT INTO custom_emoji (id, name, source_url, raw_data)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            source_url = excluded.source_url,
            updated_at = CURRENT_TIMESTAMP
    """, (
        emoji_id,
        emoji_data['customEmoji'].get('name', ''),
        emoji_data['customEmoji'].get('url'),
        json.dumps(emoji_data)
    ))
    self.conn.commit()
```

**Test**:

```python
def test_store_reaction(tmp_path):
    """Test storing reactions."""
    db = setup_test_database(tmp_path)
    storage = SyncStorage(db.conn)
    
    # Create prerequisite records
    db.conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    db.conn.execute("INSERT INTO users (id) VALUES ('user1')")
    
    reaction_data = {
        'name': 'spaces/SPACE/messages/MSG/reactions/REACT',
        'message_id': 'msg1',
        'emoji': {'content': '👍', 'unicode': 'U+1F44D'},
        'user': {'name': 'user1'},
        'createTime': '2025-01-15T10:00:00Z'
    }
    
    storage.upsert_reaction(reaction_data)
    
    # Verify
    cursor = db.conn.execute("""
        SELECT emoji_content, user_id FROM reactions WHERE id = ?
    """, (reaction_data['name'],))
    row = cursor.fetchone()
    assert row['emoji_content'] == '👍'
    assert row['user_id'] == 'user1'
```

### 3. Message Revisions (Edit History)

#### 3.1 Add Message Revisions Table

**Test**: Migration creates message revisions table

**File**: `migrations/007_message_revisions.py`

```python
# ABOUTME: Add message revisions table for edit history
# ABOUTME: Stores previous versions of edited messages

def upgrade(conn):
    """Add message revisions table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            
            revision_number INTEGER NOT NULL,
            
            text TEXT,
            formatted_text TEXT,
            
            last_update_time TIMESTAMP NOT NULL,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            
            UNIQUE(message_id, revision_number)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_revisions_message 
        ON message_revisions(message_id, revision_number)
    """)
    
    # Add revision tracking to messages table
    conn.execute("""
        ALTER TABLE messages 
        ADD COLUMN revision_number INTEGER DEFAULT 0
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS message_revisions")
    # Can't remove column in SQLite without recreating table
    conn.commit()
```

**Test**:

```python
def test_message_revisions_migration(tmp_path):
    """Test message revisions table creation."""
    from migrations.007_message_revisions import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create messages table
    conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            text TEXT,
            last_update_time TIMESTAMP
        )
    """)
    
    upgrade(conn)
    
    # Create message with revisions
    conn.execute("""
        INSERT INTO messages (id, text, last_update_time, revision_number)
        VALUES ('msg1', 'edited text', '2025-01-15T10:01:00Z', 1)
    """)
    
    conn.execute("""
        INSERT INTO message_revisions 
        (message_id, revision_number, text, last_update_time)
        VALUES ('msg1', 0, 'original text', '2025-01-15T10:00:00Z')
    """)
    
    # Verify
    cursor = conn.execute("""
        SELECT text FROM message_revisions WHERE message_id = 'msg1'
    """)
    assert cursor.fetchone()[0] == 'original text'
    
    conn.close()
```

#### 3.2 Message Revision Storage

**Test**: Can track message edits

**File**: Update `src/gchat_mirror/sync/storage.py`

```python
# Add to SyncStorage class:

def update_message(self, message_data: Dict[str, Any]):
    """
    Update an existing message, preserving old version as revision.
    
    This handles message edits by storing the old version in
    message_revisions before updating the main record.
    """
    message_id = message_data['name']
    
    # Get current version
    cursor = self.conn.execute("""
        SELECT text, formatted_text, last_update_time, revision_number
        FROM messages WHERE id = ?
    """, (message_id,))
    
    current = cursor.fetchone()
    if not current:
        # Message doesn't exist, insert it
        self.insert_message(message_data)
        return
    
    # Check if actually changed
    new_text = message_data.get('text', '')
    if current['text'] == new_text:
        # No change, skip
        return
    
    # Store current version as revision
    self.conn.execute("""
        INSERT INTO message_revisions 
        (message_id, revision_number, text, formatted_text, 
         last_update_time, raw_data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        message_id,
        current['revision_number'],
        current['text'],
        current['formatted_text'],
        current['last_update_time'],
        json.dumps({})  # Old raw_data if we had it
    ))
    
    # Update message with new content
    new_revision = current['revision_number'] + 1
    self.conn.execute("""
        UPDATE messages
        SET text = ?,
            formatted_text = ?,
            last_update_time = ?,
            revision_number = ?,
            raw_data = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        new_text,
        message_data.get('formattedText'),
        message_data.get('lastUpdateTime'),
        new_revision,
        json.dumps(message_data),
        message_id
    ))
    
    self.conn.commit()
    
    logger.info("message_updated", message_id=message_id, 
               revision=new_revision)
```

**Test**:

```python
def test_message_edit_creates_revision(tmp_path):
    """Test that editing a message creates a revision."""
    db = setup_test_database(tmp_path)
    storage = SyncStorage(db.conn)
    
    # Create initial message
    original = {
        'name': 'msg1',
        'text': 'original text',
        'lastUpdateTime': '2025-01-15T10:00:00Z',
        'sender': {'name': 'user1'}
    }
    storage.insert_message(original)
    
    # Edit the message
    edited = {
        'name': 'msg1',
        'text': 'edited text',
        'lastUpdateTime': '2025-01-15T10:01:00Z',
        'sender': {'name': 'user1'}
    }
    storage.update_message(edited)
    
    # Verify current version
    cursor = db.conn.execute("""
        SELECT text, revision_number FROM messages WHERE id = 'msg1'
    """)
    row = cursor.fetchone()
    assert row['text'] == 'edited text'
    assert row['revision_number'] == 1
    
    # Verify revision exists
    cursor = db.conn.execute("""
        SELECT text, revision_number FROM message_revisions 
        WHERE message_id = 'msg1'
    """)
    row = cursor.fetchone()
    assert row['text'] == 'original text'
    assert row['revision_number'] == 0
```

### 4. Read Receipts

#### 4.1 Add Read Receipts Table

**Test**: Migration creates read receipts table

**File**: `migrations/008_read_receipts.py`

```python
# ABOUTME: Add read receipts table for message read tracking
# ABOUTME: Stores who has read which messages and when

def upgrade(conn):
    """Add read receipts table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS read_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            read_time TIMESTAMP NOT NULL,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id),
            
            UNIQUE(message_id, user_id)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_read_receipts_message 
        ON read_receipts(message_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_read_receipts_user 
        ON read_receipts(user_id)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS read_receipts")
    conn.commit()
```

**Test**:

```python
def test_read_receipts_migration(tmp_path):
    """Test read receipts table creation."""
    from migrations.008_read_receipts import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create prerequisites
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    
    upgrade(conn)
    
    # Insert test read receipt
    conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    conn.execute("INSERT INTO users (id) VALUES ('user1')")
    conn.execute("""
        INSERT INTO read_receipts (message_id, user_id, read_time)
        VALUES ('msg1', 'user1', '2025-01-15T10:00:00Z')
    """)
    
    # Verify unique constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO read_receipts (message_id, user_id, read_time)
            VALUES ('msg1', 'user1', '2025-01-15T10:01:00Z')
        """)
    
    conn.close()
```

### 5. Notification Queue

#### 5.1 Add Notification Queue Table

**Test**: Migration creates notification queue table

**File**: `migrations/009_notification_queue.py`

```python
# ABOUTME: Add notification queue table for export client notifications
# ABOUTME: Tracks data changes that need to be exported to clients

def upgrade(conn):
    """Add notification queue table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            
            data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            
            INDEX idx_notification_queue_pending (processed_at, created_at)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_notification_queue_entity
        ON notification_queue(entity_type, entity_id)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS notification_queue")
    conn.commit()
```

**Test**:

```python
def test_notification_queue_migration(tmp_path):
    """Test notification queue table creation."""
    from migrations.009_notification_queue import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    upgrade(conn)
    
    # Insert test notification
    conn.execute("""
        INSERT INTO notification_queue 
        (entity_type, entity_id, change_type, data)
        VALUES ('message', 'msg1', 'created', '{"text": "test"}')
    """)
    
    # Query pending
    cursor = conn.execute("""
        SELECT entity_type, entity_id, change_type
        FROM notification_queue
        WHERE processed_at IS NULL
    """)
    row = cursor.fetchone()
    assert row[0] == 'message'
    assert row[1] == 'msg1'
    assert row[2] == 'created'
    
    conn.close()
```

#### 5.2 Notification Manager

**Test**: Can enqueue and process notifications

**File**: `src/gchat_mirror/common/notifications.py`

```python
# ABOUTME: Notification queue management for export clients
# ABOUTME: Handles enqueueing changes and marking them processed

import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import structlog

logger = structlog.get_logger()

class NotificationManager:
    """Manage notification queue for export clients."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def enqueue(self, entity_type: str, entity_id: str, 
                change_type: str, data: Optional[Dict] = None):
        """
        Add a notification to the queue.
        
        Args:
            entity_type: Type of entity (message, space, user, etc.)
            entity_id: ID of the entity
            change_type: Type of change (created, updated, deleted)
            data: Optional additional data
        """
        self.conn.execute("""
            INSERT INTO notification_queue 
            (entity_type, entity_id, change_type, data)
            VALUES (?, ?, ?, ?)
        """, (
            entity_type,
            entity_id,
            change_type,
            json.dumps(data) if data else None
        ))
        self.conn.commit()
        
        logger.debug("notification_enqueued",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    change_type=change_type)
    
    def get_pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get pending notifications."""
        cursor = self.conn.execute("""
            SELECT id, entity_type, entity_id, change_type, data, created_at
            FROM notification_queue
            WHERE processed_at IS NULL
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def mark_processed(self, notification_ids: List[int]):
        """Mark notifications as processed."""
        if not notification_ids:
            return
        
        placeholders = ','.join('?' * len(notification_ids))
        self.conn.execute(f"""
            UPDATE notification_queue
            SET processed_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
        """, notification_ids)
        self.conn.commit()
        
        logger.debug("notifications_processed", count=len(notification_ids))
    
    def cleanup_old(self, days: int = 30):
        """Remove processed notifications older than specified days."""
        self.conn.execute("""
            DELETE FROM notification_queue
            WHERE processed_at IS NOT NULL
              AND processed_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        self.conn.commit()
```

**Test**:

```python
def test_notification_manager(tmp_path):
    """Test notification queue operations."""
    db = setup_test_database(tmp_path)
    manager = NotificationManager(db.conn)
    
    # Enqueue notifications
    manager.enqueue('message', 'msg1', 'created', {'text': 'hello'})
    manager.enqueue('message', 'msg2', 'created', {'text': 'world'})
    
    # Get pending
    pending = manager.get_pending()
    assert len(pending) == 2
    assert pending[0]['entity_id'] == 'msg1'
    assert pending[1]['entity_id'] == 'msg2'
    
    # Mark processed
    notification_ids = [p['id'] for p in pending]
    manager.mark_processed(notification_ids)
    
    # Verify no longer pending
    pending = manager.get_pending()
    assert len(pending) == 0
```

### 6. Export Client Registration

#### 6.1 Add Client Registry Table

**Test**: Migration creates client registry table

**File**: `migrations/010_client_registry.py`

```python
# ABOUTME: Add client registry table for export client tracking
# ABOUTME: Tracks registered export clients with heartbeat monitoring

def upgrade(conn):
    """Add client registry table."""
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_clients (
            id TEXT PRIMARY KEY,
            client_type TEXT NOT NULL,
            
            status TEXT DEFAULT 'active',
            
            last_heartbeat TIMESTAMP,
            last_processed_notification INTEGER,
            
            config TEXT,
            
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_export_clients_status
        ON export_clients(status, last_heartbeat)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS export_clients")
    conn.commit()
```

**Test**:

```python
def test_client_registry_migration(tmp_path):
    """Test client registry table creation."""
    from migrations.010_client_registry import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    upgrade(conn)
    
    # Register client
    conn.execute("""
        INSERT INTO export_clients (id, client_type)
        VALUES ('discourse-1', 'discourse')
    """)
    
    cursor = conn.execute("""
        SELECT client_type, status FROM export_clients WHERE id = 'discourse-1'
    """)
    row = cursor.fetchone()
    assert row[0] == 'discourse'
    assert row[1] == 'active'
    
    conn.close()
```

#### 6.2 Client Registry Manager

**Test**: Can register and track clients

**File**: `src/gchat_mirror/common/client_registry.py`

```python
# ABOUTME: Export client registry management
# ABOUTME: Handles client registration, heartbeats, and status tracking

import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import structlog

logger = structlog.get_logger()

class ClientRegistry:
    """Manage export client registration and heartbeats."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def register(self, client_id: str, client_type: str, 
                 config: Optional[Dict] = None) -> str:
        """
        Register an export client.
        
        Returns:
            The client_id
        """
        self.conn.execute("""
            INSERT INTO export_clients 
            (id, client_type, config, last_heartbeat)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                status = 'active',
                last_heartbeat = CURRENT_TIMESTAMP,
                config = excluded.config,
                updated_at = CURRENT_TIMESTAMP
        """, (client_id, client_type, json.dumps(config) if config else None))
        self.conn.commit()
        
        logger.info("client_registered", client_id=client_id, 
                   client_type=client_type)
        
        return client_id
    
    def heartbeat(self, client_id: str, 
                  last_processed_notification: Optional[int] = None):
        """Update client heartbeat."""
        if last_processed_notification is not None:
            self.conn.execute("""
                UPDATE export_clients
                SET last_heartbeat = CURRENT_TIMESTAMP,
                    last_processed_notification = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (last_processed_notification, client_id))
        else:
            self.conn.execute("""
                UPDATE export_clients
                SET last_heartbeat = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (client_id,))
        
        self.conn.commit()
    
    def unregister(self, client_id: str):
        """Unregister a client."""
        self.conn.execute("""
            UPDATE export_clients
            SET status = 'inactive',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (client_id,))
        self.conn.commit()
        
        logger.info("client_unregistered", client_id=client_id)
    
    def list_clients(self) -> List[Dict[str, Any]]:
        """List all registered clients."""
        cursor = self.conn.execute("""
            SELECT id, client_type, status, last_heartbeat,
                   last_processed_notification, registered_at
            FROM export_clients
            ORDER BY registered_at DESC
        """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def cleanup_stale(self, timeout_minutes: int = 10):
        """Mark clients as stale if no heartbeat received."""
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)
        
        cursor = self.conn.execute("""
            UPDATE export_clients
            SET status = 'stale'
            WHERE status = 'active'
              AND last_heartbeat < ?
        """, (cutoff,))
        
        stale_count = cursor.rowcount
        self.conn.commit()
        
        if stale_count > 0:
            logger.warning("clients_marked_stale", count=stale_count)
        
        return stale_count
```

**Test**:

```python
def test_client_registry(tmp_path):
    """Test client registration and management."""
    db = setup_test_database(tmp_path)
    registry = ClientRegistry(db.conn)
    
    # Register client
    client_id = registry.register('discourse-1', 'discourse',
                                 {'url': 'https://discourse.example.com'})
    assert client_id == 'discourse-1'
    
    # List clients
    clients = registry.list_clients()
    assert len(clients) == 1
    assert clients[0]['id'] == 'discourse-1'
    assert clients[0]['status'] == 'active'
    
    # Heartbeat
    registry.heartbeat('discourse-1', last_processed_notification=42)
    
    # Verify heartbeat updated
    cursor = db.conn.execute("""
        SELECT last_processed_notification FROM export_clients 
        WHERE id = 'discourse-1'
    """)
    assert cursor.fetchone()[0] == 42
    
    # Unregister
    registry.unregister('discourse-1')
    
    clients = registry.list_clients()
    assert clients[0]['status'] == 'inactive'
```

### 7. Integration with Sync Daemon

#### 7.1 Update Sync to Send Notifications

**Test**: Sync daemon enqueues notifications

**File**: Update `src/gchat_mirror/sync/storage.py`

```python
# Update SyncStorage class to use NotificationManager

from gchat_mirror.common.notifications import NotificationManager

class SyncStorage:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.notifications = NotificationManager(conn)
    
    def insert_message(self, message_data: Dict[str, Any]):
        """Insert a message and enqueue notification."""
        # ... existing insert logic ...
        
        # Enqueue notification
        self.notifications.enqueue(
            'message',
            message_data['name'],
            'created',
            {'space_id': message_data.get('space')}
        )
    
    def update_message(self, message_data: Dict[str, Any]):
        """Update message and enqueue notification."""
        # ... existing update logic ...
        
        # Enqueue notification
        self.notifications.enqueue(
            'message',
            message_data['name'],
            'updated'
        )
    
    def upsert_reaction(self, reaction_data: Dict[str, Any]):
        """Insert/update reaction and enqueue notification."""
        # ... existing upsert logic ...
        
        # Enqueue notification
        self.notifications.enqueue(
            'reaction',
            reaction_data['name'],
            'created'
        )
```

**Test**:

```python
def test_sync_creates_notifications(tmp_path):
    """Test that sync operations create notifications."""
    db = setup_test_database(tmp_path)
    storage = SyncStorage(db.conn)
    
    # Insert message
    message_data = {
        'name': 'msg1',
        'text': 'test',
        'sender': {'name': 'user1'},
        'space': 'space1'
    }
    storage.insert_message(message_data)
    
    # Check notification was created
    pending = storage.notifications.get_pending()
    assert len(pending) == 1
    assert pending[0]['entity_type'] == 'message'
    assert pending[0]['entity_id'] == 'msg1'
    assert pending[0]['change_type'] == 'created'
```

### 8. Update CLI Commands

#### 8.1 Client Management Commands

**Test**: Can list and unregister clients

**File**: Update `src/gchat_mirror/cli/clients.py`

```python
# ABOUTME: CLI commands for managing export clients
# ABOUTME: Lists and unregisters export clients with status display

import click
import sqlite3
from pathlib import Path
from rich.console import Console
from rich.table import Table
from datetime import datetime

from gchat_mirror.common.client_registry import ClientRegistry

@click.group()
def clients():
    """Export client management."""
    pass

@clients.command()
@click.pass_context
def list(ctx):
    """List registered export clients."""
    data_dir = ctx.obj['data_dir']
    db_path = data_dir / 'sync' / 'chat.db'
    
    if not db_path.exists():
        click.echo("No database found. Run sync first.")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    registry = ClientRegistry(conn)
    client_list = registry.list_clients()
    
    if not client_list:
        click.echo("No export clients registered.")
        return
    
    # Display with rich table
    console = Console()
    table = Table(title="Export Clients")
    
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Last Heartbeat")
    table.add_column("Last Notification")
    
    for client in client_list:
        heartbeat = client['last_heartbeat'] or 'Never'
        if heartbeat != 'Never':
            # Format relative time
            hb_time = datetime.fromisoformat(heartbeat)
            delta = datetime.now() - hb_time
            if delta.total_seconds() < 60:
                heartbeat = f"{int(delta.total_seconds())}s ago"
            elif delta.total_seconds() < 3600:
                heartbeat = f"{int(delta.total_seconds() / 60)}m ago"
            else:
                heartbeat = f"{int(delta.total_seconds() / 3600)}h ago"
        
        table.add_row(
            client['id'],
            client['client_type'],
            client['status'],
            heartbeat,
            str(client['last_processed_notification'] or 'None')
        )
    
    console.print(table)
    conn.close()

@clients.command()
@click.argument('client_id')
@click.pass_context
def unregister(ctx, client_id: str):
    """Unregister an export client."""
    data_dir = ctx.obj['data_dir']
    db_path = data_dir / 'sync' / 'chat.db'
    
    if not db_path.exists():
        click.echo("No database found.")
        return
    
    conn = sqlite3.connect(db_path)
    registry = ClientRegistry(conn)
    
    registry.unregister(client_id)
    click.echo(f"Client {client_id} unregistered.")
    
    conn.close()
```

**Test**:

```python
def test_clients_list_command(tmp_path):
    """Test clients list command."""
    from click.testing import CliRunner
    from gchat_mirror.cli.main import cli
    
    # Setup database with clients
    db_path = tmp_path / 'data' / 'sync' / 'chat.db'
    db_path.parent.mkdir(parents=True)
    
    conn = sqlite3.connect(db_path)
    # Run migration
    from migrations.010_client_registry import upgrade
    upgrade(conn)
    
    # Add test client
    conn.execute("""
        INSERT INTO export_clients (id, client_type, status, last_heartbeat)
        VALUES ('test-client', 'discourse', 'active', CURRENT_TIMESTAMP)
    """)
    conn.commit()
    conn.close()
    
    runner = CliRunner()
    result = runner.invoke(cli, [
        '--data-dir', str(tmp_path / 'data'),
        'clients', 'list'
    ])
    
    assert result.exit_code == 0
    assert 'test-client' in result.output
    assert 'discourse' in result.output
```

## Completion Criteria

- [ ] User avatars table created with history tracking
- [ ] Avatar downloader implemented with URL change detection
- [ ] Reactions table created and storage working
- [ ] Custom emoji table created with download tracking
- [ ] Message revisions table created
- [ ] Message edit history preserved in revisions
- [ ] Read receipts table created and storage working
- [ ] Notification queue table created
- [ ] NotificationManager implemented for enqueueing changes
- [ ] Client registry table created
- [ ] ClientRegistry manager implemented
- [ ] Sync daemon updated to send notifications
- [ ] CLI commands for client management working
- [ ] All migrations run successfully in sequence
- [ ] All unit tests pass
- [ ] Integration tests verify notifications sent

## Next Steps

After Phase 2-4 completion, Phase 2 is complete. Proceed to Phase 3: Real-time Sync, which adds adaptive polling, error handling, backfill, and monitoring.
