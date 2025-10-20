# Phase 2 Part 2: Attachment Storage Implementation

## Overview

Implement the attachment storage module that handles storing and retrieving binary data with inline/chunked strategies.

## Tasks

### 2.1 Attachment Storage Module

**Test**: Can store and retrieve attachments (inline and chunked)

**File**: `src/gchat_mirror/sync/attachment_storage.py`

```python
# ABOUTME: Attachment storage operations for inline and chunked storage
# ABOUTME: Handles storing and retrieving binary data from attachments.db

import sqlite3
import hashlib
from typing import Optional
import structlog

logger = structlog.get_logger()

INLINE_THRESHOLD = 1024 * 1024  # 1MB
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB

class AttachmentStorage:
    """Manage attachment storage in attachments.db."""
    
    def __init__(self, attachments_conn: sqlite3.Connection, 
                 chat_conn: sqlite3.Connection):
        self.attachments_conn = attachments_conn
        self.chat_conn = chat_conn
    
    def store_attachment(self, attachment_id: str, message_id: str,
                        metadata: dict, file_data: bytes):
        """
        Store an attachment with appropriate strategy.
        
        Args:
            attachment_id: Google's attachment ID
            message_id: Parent message ID
            metadata: Dict with name, content_type, source_url
            file_data: bytes of the file
        """
        size = len(file_data)
        sha256 = hashlib.sha256(file_data).hexdigest()
        
        storage_type = 'inline' if size < INLINE_THRESHOLD else 'chunked'
        
        try:
            if storage_type == 'inline':
                self._store_inline(attachment_id, message_id, metadata, 
                                 file_data, sha256, size)
            else:
                self._store_chunked(attachment_id, message_id, metadata,
                                  file_data, sha256, size)
            
            logger.info("attachment_stored", 
                       attachment_id=attachment_id,
                       size=size,
                       storage_type=storage_type)
        
        except Exception as e:
            logger.error("attachment_storage_failed",
                        attachment_id=attachment_id,
                        error=str(e))
            
            # Mark as failed in metadata
            self.chat_conn.execute("""
                UPDATE attachments 
                SET download_error = ?,
                    download_attempts = download_attempts + 1
                WHERE id = ?
            """, (str(e), attachment_id))
            self.chat_conn.commit()
            raise
    
    def _store_inline(self, attachment_id: str, message_id: str,
                     metadata: dict, file_data: bytes, 
                     sha256: str, size: int):
        """Store small attachment inline."""
        # Store metadata in chat.db
        self.chat_conn.execute("""
            INSERT INTO attachments 
            (id, message_id, name, content_type, size_bytes,
             storage_type, downloaded, download_time, sha256_hash,
             source_url, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP, ?, ?, ?)
        """, (attachment_id, message_id, metadata.get('name'),
              metadata.get('content_type'), size, 'inline', sha256,
              metadata.get('source_url'), metadata.get('raw_data', '{}')))
        
        # Store data in attachments.db
        self.attachments_conn.execute("""
            INSERT INTO attachment_inline (attachment_id, data)
            VALUES (?, ?)
        """, (attachment_id, file_data))
        
        self.chat_conn.commit()
        self.attachments_conn.commit()
    
    def _store_chunked(self, attachment_id: str, message_id: str,
                      metadata: dict, file_data: bytes,
                      sha256: str, size: int):
        """Store large attachment in chunks."""
        total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        # Store metadata in chat.db
        self.chat_conn.execute("""
            INSERT INTO attachments 
            (id, message_id, name, content_type, size_bytes,
             storage_type, chunk_size, total_chunks,
             downloaded, download_time, sha256_hash,
             source_url, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP, ?, ?, ?)
        """, (attachment_id, message_id, metadata.get('name'),
              metadata.get('content_type'), size, 'chunked',
              CHUNK_SIZE, total_chunks, sha256,
              metadata.get('source_url'), metadata.get('raw_data', '{}')))
        
        # Store chunks in attachments.db
        for i in range(total_chunks):
            start = i * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, size)
            chunk_data = file_data[start:end]
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()
            
            self.attachments_conn.execute("""
                INSERT INTO attachment_chunks 
                (attachment_id, chunk_index, data, size_bytes, sha256_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (attachment_id, i, chunk_data, len(chunk_data), chunk_hash))
        
        self.chat_conn.commit()
        self.attachments_conn.commit()
    
    def retrieve_attachment(self, attachment_id: str) -> bytes:
        """
        Retrieve complete attachment data.
        
        Returns:
            bytes: The complete file data
        
        Raises:
            ValueError: If attachment not found or not downloaded
        """
        # Get metadata from chat.db
        cursor = self.chat_conn.execute("""
            SELECT storage_type, size_bytes, sha256_hash, downloaded
            FROM attachments WHERE id = ?
        """, (attachment_id,))
        
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Attachment {attachment_id} not found")
        
        storage_type, size_bytes, expected_hash, downloaded = row
        
        if not downloaded:
            raise ValueError(f"Attachment {attachment_id} not yet downloaded")
        
        # Retrieve from attachments.db
        if storage_type == 'inline':
            data = self._retrieve_inline(attachment_id)
        else:
            data = self._retrieve_chunked(attachment_id)
        
        # Verify integrity
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"Hash mismatch for {attachment_id}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        
        return data
    
    def _retrieve_inline(self, attachment_id: str) -> bytes:
        """Retrieve inline attachment."""
        cursor = self.attachments_conn.execute("""
            SELECT data FROM attachment_inline WHERE attachment_id = ?
        """, (attachment_id,))
        
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Attachment data missing for {attachment_id}")
        
        return result[0]
    
    def _retrieve_chunked(self, attachment_id: str) -> bytes:
        """Retrieve chunked attachment."""
        cursor = self.attachments_conn.execute("""
            SELECT data FROM attachment_chunks 
            WHERE attachment_id = ? 
            ORDER BY chunk_index
        """, (attachment_id,))
        
        chunks = [row[0] for row in cursor.fetchall()]
        if not chunks:
            raise ValueError(f"No chunks found for {attachment_id}")
        
        return b''.join(chunks)
```

**Tests**:

```python
def test_store_and_retrieve_small_attachment(tmp_path):
    """Test inline storage for small files."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Create small test file
    test_data = b"Hello world! " * 100  # < 1MB
    metadata = {
        'name': 'small.txt',
        'content_type': 'text/plain',
        'source_url': 'https://example.com/file'
    }
    
    # Store
    storage.store_attachment('att1', 'msg1', metadata, test_data)
    
    # Retrieve
    retrieved = storage.retrieve_attachment('att1')
    
    assert retrieved == test_data
    
    # Verify metadata
    cursor = chat_db.conn.execute("""
        SELECT storage_type, size_bytes, downloaded
        FROM attachments WHERE id = ?
    """, ('att1',))
    row = cursor.fetchone()
    assert row['storage_type'] == 'inline'
    assert row['size_bytes'] == len(test_data)
    assert row['downloaded'] == 1

def test_store_and_retrieve_large_attachment(tmp_path):
    """Test chunked storage for large files."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Create large test file (15MB)
    test_data = b"X" * (15 * 1024 * 1024)
    metadata = {
        'name': 'large.bin',
        'content_type': 'application/octet-stream',
        'source_url': 'https://example.com/largefile'
    }
    
    # Store
    storage.store_attachment('att2', 'msg2', metadata, test_data)
    
    # Retrieve
    retrieved = storage.retrieve_attachment('att2')
    
    assert retrieved == test_data
    
    # Verify it was chunked
    cursor = chat_db.conn.execute("""
        SELECT storage_type, total_chunks
        FROM attachments WHERE id = ?
    """, ('att2',))
    row = cursor.fetchone()
    assert row['storage_type'] == 'chunked'
    assert row['total_chunks'] == 2  # 15MB / 10MB = 2 chunks

def test_attachment_integrity_check(tmp_path):
    """Test that corrupted data is detected."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Store attachment
    test_data = b"test data"
    storage.store_attachment('att3', 'msg3', 
                            {'name': 'test.txt'}, test_data)
    
    # Corrupt the data
    att_db.conn.execute("""
        UPDATE attachment_inline 
        SET data = ?
        WHERE attachment_id = ?
    """, (b"corrupted", 'att3'))
    att_db.conn.commit()
    
    # Try to retrieve - should fail hash check
    with pytest.raises(ValueError, match="Hash mismatch"):
        storage.retrieve_attachment('att3')
```

## Completion Criteria

- [ ] AttachmentStorage class implemented
- [ ] Inline storage works for files < 1MB
- [ ] Chunked storage works for files >= 1MB
- [ ] SHA256 integrity checks work
- [ ] Error handling and logging in place
- [ ] All tests pass
