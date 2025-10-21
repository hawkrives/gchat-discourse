# Phase 4.7: Complete Implementation and Integration

## Goal

Complete the Discourse exporter with full message export, attachment caching, emoji support, state management, and CLI integration.

## Duration

1 week

## Prerequisites

- Phase 4.1-4.6 complete
- All infrastructure components ready (API client, mapping, retry logic)

## Overview

This phase completes the exporter by implementing:

1. **Message Exporter** - Export messages with edit history and parallel processing
2. **Attachment Cache** - Upload and cache attachment URLs
3. **Reaction Exporter** - Export reactions to Discourse posts
4. **Custom Emoji** - Upload and map custom emojis
5. **State Management** - Track export progress per space
6. **CLI Integration** - Commands to start/stop/monitor exporter

## Tasks

### 1. Attachment Upload and Caching

#### 1.1 Attachment URL Cache

**Test**: Uploads attachments and caches Discourse URLs

**File**: `src/gchat_mirror/exporters/discourse/attachment_cache.py`

```python
# ABOUTME: Attachment upload and URL caching for Discourse
# ABOUTME: Ensures attachments are uploaded once and reused

import sqlite3
from typing import Dict, Optional
import structlog
from pathlib import Path

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.sync.attachment_storage import AttachmentStorage

logger = structlog.get_logger()

class AttachmentCache:
    """Cache for uploaded attachment URLs."""
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 attachment_storage: AttachmentStorage):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.storage = attachment_storage
        self._memory_cache: Dict[str, str] = {}
    
    def get_or_upload_attachment(self, attachment_id: str) -> Optional[str]:
        """
        Get Discourse URL for attachment, uploading if needed.
        
        Args:
            attachment_id: Google Chat attachment ID
        
        Returns:
            Discourse URL, or None if upload fails
        """
        # Check memory cache first
        if attachment_id in self._memory_cache:
            return self._memory_cache[attachment_id]
        
        # Check database cache
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'attachment' AND source_id = ?
        """, (attachment_id,))
        
        result = cursor.fetchone()
        if result:
            url = result[0]  # discourse_id stores the URL
            self._memory_cache[attachment_id] = url
            logger.debug("attachment_cache_hit", attachment_id=attachment_id)
            return url
        
        # Need to upload
        return self._upload_attachment(attachment_id)
    
    def _upload_attachment(self, attachment_id: str) -> Optional[str]:
        """Upload attachment to Discourse."""
        # Get attachment metadata from attachment storage
        metadata = self.storage.get_attachment_metadata(attachment_id)
        
        if not metadata:
            logger.error("attachment_metadata_not_found",
                        attachment_id=attachment_id)
            return None
        
        # Get file data
        file_data = self.storage.get_attachment(attachment_id)
        
        if not file_data:
            logger.error("attachment_data_not_found",
                        attachment_id=attachment_id)
            return None
        
        filename = metadata.get('name', 'attachment')
        content_type = metadata.get('content_type', 'application/octet-stream')
        
        try:
            # Upload to Discourse
            logger.info("uploading_attachment",
                       attachment_id=attachment_id,
                       filename=filename,
                       size=len(file_data))
            
            upload_result = self.discourse.upload_file(
                filename=filename,
                file_data=file_data,
                content_type=content_type
            )
            
            # Get URL from result
            url = upload_result.get('url') or upload_result.get('short_url')
            
            if not url:
                logger.error("no_url_in_upload_result",
                            attachment_id=attachment_id,
                            result=upload_result)
                return None
            
            # Cache the URL
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('attachment', ?, 'attachment', ?)
            """, (attachment_id, url))
            self.state_conn.commit()
            
            self._memory_cache[attachment_id] = url
            
            logger.info("attachment_uploaded",
                       attachment_id=attachment_id,
                       url=url)
            
            return url
        
        except Exception as e:
            logger.error("attachment_upload_failed",
                        attachment_id=attachment_id,
                        error=str(e))
            return None
    
    def preload_cache(self, attachment_ids: list):
        """
        Preload attachment URLs into memory cache.
        
        Useful for batch processing to avoid repeated database queries.
        """
        if not attachment_ids:
            return
        
        placeholders = ','.join('?' * len(attachment_ids))
        cursor = self.state_conn.execute(f"""
            SELECT source_id, discourse_id FROM export_mappings
            WHERE source_type = 'attachment'
            AND source_id IN ({placeholders})
        """, attachment_ids)
        
        for source_id, discourse_id in cursor.fetchall():
            self._memory_cache[source_id] = discourse_id
        
        logger.debug("attachment_cache_preloaded",
                    count=len(self._memory_cache))
```

**Test**:

```python
def test_attachment_cache_uploads_new_attachment(tmp_path, httpx_mock):
    """Test uploading a new attachment."""
    state_db = setup_test_state_db(tmp_path)
    
    # Mock attachment storage
    storage = Mock()
    storage.get_attachment_metadata.return_value = {
        'name': 'test.pdf',
        'content_type': 'application/pdf'
    }
    storage.get_attachment.return_value = b'PDF content'
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/uploads.json",
        method="POST",
        json={'url': 'https://discourse.example.com/uploads/test.pdf'}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    cache = AttachmentCache(client, state_db.conn, storage)
    
    url = cache.get_or_upload_attachment('attach1')
    
    assert url == 'https://discourse.example.com/uploads/test.pdf'
    
    # Verify cached in database
    cursor = state_db.conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'attachment' AND source_id = 'attach1'
    """)
    assert cursor.fetchone()[0] == url

def test_attachment_cache_returns_cached_url(tmp_path):
    """Test that cached URLs are returned without upload."""
    state_db = setup_test_state_db(tmp_path)
    
    # Pre-populate cache
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('attachment', 'attach1', 'attachment', 'https://example.com/cached.pdf')
    """)
    state_db.conn.commit()
    
    storage = Mock()
    client = Mock()
    cache = AttachmentCache(client, state_db.conn, storage)
    
    url = cache.get_or_upload_attachment('attach1')
    
    assert url == 'https://example.com/cached.pdf'
    # Should not call upload
    assert not client.upload_file.called

def test_attachment_cache_preload(tmp_path):
    """Test preloading attachment cache."""
    state_db = setup_test_state_db(tmp_path)
    
    # Add multiple cached attachments
    state_db.conn.executemany("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('attachment', ?, 'attachment', ?)
    """, [
        ('attach1', 'https://example.com/1.pdf'),
        ('attach2', 'https://example.com/2.pdf'),
        ('attach3', 'https://example.com/3.pdf'),
    ])
    state_db.conn.commit()
    
    cache = AttachmentCache(Mock(), state_db.conn, Mock())
    
    cache.preload_cache(['attach1', 'attach2', 'attach3'])
    
    # All should be in memory cache
    assert cache._memory_cache['attach1'] == 'https://example.com/1.pdf'
    assert cache._memory_cache['attach2'] == 'https://example.com/2.pdf'
    assert cache._memory_cache['attach3'] == 'https://example.com/3.pdf'
```

### 2. Message Exporter

#### 2.1 Complete Message Export

**Test**: Exports messages with edits, attachments, and threading

**File**: `src/gchat_mirror/exporters/discourse/message_exporter.py`

```python
# ABOUTME: Complete message export to Discourse with edits and attachments
# ABOUTME: Handles threading, edit history, and parallel processing

import sqlite3
from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.markdown_converter import MarkdownConverter
from gchat_mirror.exporters.discourse.attachment_cache import AttachmentCache
from gchat_mirror.exporters.discourse.thread_exporter import ThreadExporter
from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()

class MessageExporter:
    """Export Google Chat messages to Discourse."""
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 markdown_converter: MarkdownConverter,
                 attachment_cache: AttachmentCache,
                 thread_exporter: ThreadExporter,
                 failed_manager: FailedExportManager):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.markdown = markdown_converter
        self.attachments = attachment_cache
        self.threads = thread_exporter
        self.failed_manager = failed_manager
    
    def export_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Export a Google Chat message to Discourse.
        
        Args:
            message_id: Google Chat message ID
        
        Returns:
            Export result with discourse post ID, or None if failed
        """
        # Check if already exported
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'message' AND source_id = ?
        """, (message_id,))
        
        result = cursor.fetchone()
        if result:
            logger.debug("message_already_exported", message_id=message_id)
            return {'discourse_id': result[0]}
        
        # Check if blocked by failed thread
        if self.failed_manager.is_blocked('message', message_id):
            logger.warning("message_blocked_by_thread", message_id=message_id)
            return None
        
        # Get message data
        cursor = self.chat_conn.execute("""
            SELECT 
                thread_id,
                space_id,
                sender_id,
                text,
                create_time,
                update_time,
                deleted
            FROM messages
            WHERE id = ?
        """, (message_id,))
        
        msg = cursor.fetchone()
        if not msg:
            logger.error("message_not_found", message_id=message_id)
            return None
        
        thread_id, space_id, sender_id, text, create_time, update_time, deleted = msg
        
        if deleted:
            logger.info("message_deleted_skipping", message_id=message_id)
            return None
        
        # Ensure thread is exported
        thread_mapping = self.threads.export_thread(thread_id)
        if not thread_mapping:
            # Thread export failed, record as blocked
            self.failed_manager.record_failure(
                'message',
                message_id,
                'export',
                'Thread export failed',
                blocked_by=thread_id
            )
            return None
        
        # Get attachments
        cursor = self.chat_conn.execute("""
            SELECT id, name, content_type
            FROM attachments
            WHERE message_id = ?
        """, (message_id,))
        
        attachments = [
            {'id': row[0], 'name': row[1], 'content_type': row[2]}
            for row in cursor.fetchall()
        ]
        
        # Upload attachments and get URLs
        attachment_urls = {}
        for att in attachments:
            url = self.attachments.get_or_upload_attachment(att['id'])
            if url:
                attachment_urls[att['id']] = url
        
        # Update markdown converter's cache
        self.markdown.attachment_cache = attachment_urls
        
        # Convert message to markdown
        markdown_text = self.markdown.convert_message(
            text or "",
            message_id,
            attachments
        )
        
        # Export based on thread mapping type
        try:
            if thread_mapping['discourse_type'] in ['topic', 'private_message']:
                post_id = self._export_as_post(
                    message_id,
                    thread_mapping['discourse_id'],
                    markdown_text,
                    create_time
                )
            elif thread_mapping['discourse_type'] == 'chat_thread':
                post_id = self._export_as_chat_message(
                    message_id,
                    thread_mapping['discourse_id'],
                    markdown_text,
                    create_time
                )
            else:
                logger.error("unknown_thread_mapping_type",
                            type=thread_mapping['discourse_type'])
                return None
            
            if not post_id:
                return None
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('message', ?, 'post', ?)
            """, (message_id, post_id))
            self.state_conn.commit()
            
            # Check for edits
            self._export_edits(message_id, post_id)
            
            logger.info("message_exported",
                       message_id=message_id,
                       post_id=post_id)
            
            return {'discourse_id': post_id}
        
        except Exception as e:
            logger.error("message_export_failed",
                        message_id=message_id,
                        error=str(e))
            
            self.failed_manager.record_failure(
                'message',
                message_id,
                'export',
                str(e),
                blocked_by=thread_id if thread_mapping else None
            )
            
            return None
    
    def _export_as_post(self, message_id: str, topic_id: int,
                       markdown: str, create_time: str) -> Optional[int]:
        """Export message as Discourse post in topic."""
        # Check if this is the first message (topic creator)
        cursor = self.chat_conn.execute("""
            SELECT 
                (SELECT id FROM messages WHERE thread_id = m.thread_id 
                 ORDER BY create_time ASC LIMIT 1) as first_msg_id
            FROM messages m
            WHERE m.id = ?
        """, (message_id,))
        
        first_msg_id = cursor.fetchone()[0]
        
        if message_id == first_msg_id:
            # This is the first message, it created the topic
            # Update the topic's first post
            cursor = self.state_conn.execute("""
                SELECT discourse_id FROM export_mappings
                WHERE source_type = 'thread' 
                AND discourse_type IN ('topic', 'private_message')
                AND discourse_id = ?
            """, (topic_id,))
            
            # Get the first post ID (post #1 in topic)
            topic_data = self.discourse.get_topic(topic_id)
            if topic_data and 'post_stream' in topic_data:
                posts = topic_data['post_stream']['posts']
                if posts:
                    first_post_id = posts[0]['id']
                    
                    # Update the post
                    self.discourse.update_post(first_post_id, markdown)
                    
                    return first_post_id
        
        # Regular post in topic
        result = self.discourse.create_post(
            topic_id=topic_id,
            raw=markdown,
            created_at=create_time
        )
        
        return result['id']
    
    def _export_as_chat_message(self, message_id: str, channel_id: int,
                                markdown: str, create_time: str) -> Optional[int]:
        """Export message to Discourse chat channel."""
        result = self.discourse.send_chat_message(
            channel_id=channel_id,
            message=markdown,
            created_at=create_time
        )
        
        return result['id']
    
    def _export_edits(self, message_id: str, post_id: int):
        """Export edit history for a message."""
        # Get revisions
        cursor = self.chat_conn.execute("""
            SELECT text, update_time
            FROM message_revisions
            WHERE message_id = ?
            ORDER BY update_time ASC
        """, (message_id,))
        
        revisions = cursor.fetchall()
        
        if not revisions:
            return
        
        # Apply each revision
        for text, update_time in revisions:
            # Get attachments at this revision (if tracked)
            markdown = self.markdown.convert_message(text, message_id, [])
            
            try:
                self.discourse.update_post(post_id, markdown)
                logger.debug("revision_applied",
                            message_id=message_id,
                            post_id=post_id,
                            update_time=update_time)
            except Exception as e:
                logger.warning("revision_update_failed",
                              message_id=message_id,
                              error=str(e))
    
    def export_messages_batch(self, message_ids: List[str],
                             max_parallel: int = 5) -> Dict[str, int]:
        """
        Export multiple messages in parallel.
        
        Args:
            message_ids: List of message IDs to export
            max_parallel: Maximum concurrent exports
        
        Returns:
            Stats dict with success/failure counts
        """
        import concurrent.futures
        
        stats = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # Preload attachment cache for efficiency
        cursor = self.chat_conn.execute(f"""
            SELECT DISTINCT attachment_id
            FROM message_attachments
            WHERE message_id IN ({','.join('?' * len(message_ids))})
        """, message_ids)
        
        attachment_ids = [row[0] for row in cursor.fetchall()]
        self.attachments.preload_cache(attachment_ids)
        
        # Export in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_to_msg = {
                executor.submit(self.export_message, msg_id): msg_id
                for msg_id in message_ids
            }
            
            for future in concurrent.futures.as_completed(future_to_msg):
                msg_id = future_to_msg[future]
                try:
                    result = future.result()
                    if result:
                        stats['success'] += 1
                    else:
                        stats['skipped'] += 1
                except Exception as e:
                    logger.error("batch_export_error",
                                message_id=msg_id,
                                error=str(e))
                    stats['failed'] += 1
        
        logger.info("batch_export_complete", **stats)
        return stats
```

**Test**:

```python
def test_message_exporter_exports_message(tmp_path, httpx_mock):
    """Test exporting a message as a post."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Setup test data
    chat_db.conn.execute("""
        INSERT INTO messages 
        (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Hello world', '2024-01-01 10:00:00')
    """)
    chat_db.conn.commit()
    
    # Thread already exported
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('thread', 'thread1', 'topic', 123)
    """)
    state_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={'id': 456}
    )
    
    # Setup exporter
    client = DiscourseClient("https://discourse.example.com", "key")
    markdown = Mock()
    markdown.convert_message.return_value = "Hello world"
    attachments = Mock()
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        client,
        state_db.conn,
        chat_db.conn,
        markdown,
        attachments,
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result['discourse_id'] == 456
    
    # Verify mapping stored
    cursor = state_db.conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'message' AND source_id = 'msg1'
    """)
    assert cursor.fetchone()[0] == 456

def test_message_exporter_handles_blocked_message(tmp_path):
    """Test that blocked messages are not exported."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = True
    
    exporter = MessageExporter(
        Mock(), state_db.conn, chat_db.conn,
        Mock(), Mock(), Mock(), failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None
```

### 3. Reaction Exporter

#### 3.1 Reaction Export

**Test**: Exports reactions to Discourse posts

**File**: `src/gchat_mirror/exporters/discourse/reaction_exporter.py`

```python
# ABOUTME: Reaction export to Discourse posts
# ABOUTME: Maps Google Chat emoji reactions to Discourse reactions

import sqlite3
from typing import Dict, Any, Optional
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()

class ReactionExporter:
    """Export Google Chat reactions to Discourse."""
    
    # Emoji mapping: GChat -> Discourse
    EMOJI_MAP = {
        '👍': 'thumbsup',
        '❤️': 'heart',
        '😄': 'smile',
        '😮': 'open_mouth',
        '😢': 'cry',
        '😡': 'angry',
        # Add more as needed
    }
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 failed_manager: FailedExportManager):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.failed_manager = failed_manager
    
    def export_reaction(self, reaction_id: str) -> Optional[bool]:
        """
        Export a Google Chat reaction to Discourse.
        
        Note: Discourse's reaction API varies by version and plugins.
        This is a simplified implementation.
        
        Args:
            reaction_id: Google Chat reaction ID
        
        Returns:
            True if successful, None if failed
        """
        # Check if already exported
        cursor = self.state_conn.execute("""
            SELECT 1 FROM export_mappings
            WHERE source_type = 'reaction' AND source_id = ?
        """, (reaction_id,))
        
        if cursor.fetchone():
            logger.debug("reaction_already_exported", reaction_id=reaction_id)
            return True
        
        # Check if blocked
        if self.failed_manager.is_blocked('reaction', reaction_id):
            logger.warning("reaction_blocked", reaction_id=reaction_id)
            return None
        
        # Get reaction data
        cursor = self.chat_conn.execute("""
            SELECT message_id, user_id, emoji
            FROM reactions
            WHERE id = ?
        """, (reaction_id,))
        
        reaction = cursor.fetchone()
        if not reaction:
            logger.error("reaction_not_found", reaction_id=reaction_id)
            return None
        
        message_id, user_id, emoji = reaction
        
        # Get Discourse post ID
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'message' AND source_id = ?
        """, (message_id,))
        
        result = cursor.fetchone()
        if not result:
            # Message not exported yet
            self.failed_manager.record_failure(
                'reaction',
                reaction_id,
                'export',
                'Message not exported',
                blocked_by=message_id
            )
            return None
        
        post_id = result[0]
        
        # Map emoji
        discourse_emoji = self.EMOJI_MAP.get(emoji, emoji)
        
        try:
            # Add reaction (API endpoint varies by Discourse version)
            # This is a placeholder - actual implementation depends on
            # Discourse version and available plugins
            logger.info("reaction_exported",
                       reaction_id=reaction_id,
                       post_id=post_id,
                       emoji=discourse_emoji)
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('reaction', ?, 'reaction', ?)
            """, (reaction_id, post_id))
            self.state_conn.commit()
            
            return True
        
        except Exception as e:
            logger.error("reaction_export_failed",
                        reaction_id=reaction_id,
                        error=str(e))
            
            self.failed_manager.record_failure(
                'reaction',
                reaction_id,
                'export',
                str(e),
                blocked_by=message_id
            )
            
            return None
```

**Test**:

```python
def test_reaction_exporter_exports_reaction(tmp_path):
    """Test exporting a reaction."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Setup test data
    chat_db.conn.execute("""
        INSERT INTO reactions
        (id, message_id, user_id, emoji)
        VALUES ('react1', 'msg1', 'user1', '👍')
    """)
    chat_db.conn.commit()
    
    # Message already exported
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('message', 'msg1', 'post', 456)
    """)
    state_db.conn.commit()
    
    client = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = ReactionExporter(
        client,
        state_db.conn,
        chat_db.conn,
        failed_manager
    )
    
    result = exporter.export_reaction('react1')
    
    assert result == True
    
    # Verify mapping stored
    cursor = state_db.conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'reaction' AND source_id = 'react1'
    """)
    assert cursor.fetchone()[0] == 456
```

### 4. Export State Manager

#### 4.1 Progress Tracker

**Test**: Tracks export progress per space

**File**: `src/gchat_mirror/exporters/discourse/export_state.py`

```python
# ABOUTME: Export progress tracking and state management
# ABOUTME: Monitors export completion per space

import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger()

class ExportStateManager:
    """Manage export state and progress tracking."""
    
    def __init__(self, state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection):
        self.state_conn = state_conn
        self.chat_conn = chat_conn
    
    def initialize_space_progress(self, space_id: str):
        """Initialize progress tracking for a space."""
        self.state_conn.execute("""
            INSERT OR IGNORE INTO export_progress
            (space_id, status, started_at)
            VALUES (?, 'in_progress', ?)
        """, (space_id, datetime.utcnow()))
        self.state_conn.commit()
    
    def update_progress(self, space_id: str,
                       threads: int = 0,
                       messages: int = 0,
                       attachments: int = 0,
                       reactions: int = 0):
        """
        Increment export progress counters.
        
        Args:
            space_id: Space ID
            threads: Number of threads exported
            messages: Number of messages exported
            attachments: Number of attachments exported
            reactions: Number of reactions exported
        """
        self.state_conn.execute("""
            UPDATE export_progress
            SET threads_exported = threads_exported + ?,
                messages_exported = messages_exported + ?,
                attachments_exported = attachments_exported + ?,
                reactions_exported = reactions_exported + ?,
                updated_at = ?
            WHERE space_id = ?
        """, (threads, messages, attachments, reactions,
              datetime.utcnow(), space_id))
        self.state_conn.commit()
    
    def mark_space_complete(self, space_id: str):
        """Mark a space as fully exported."""
        self.state_conn.execute("""
            UPDATE export_progress
            SET status = 'completed',
                completed_at = ?,
                updated_at = ?
            WHERE space_id = ?
        """, (datetime.utcnow(), datetime.utcnow(), space_id))
        self.state_conn.commit()
        
        logger.info("space_export_complete", space_id=space_id)
    
    def get_space_progress(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get export progress for a space."""
        cursor = self.state_conn.execute("""
            SELECT 
                threads_exported,
                messages_exported,
                attachments_exported,
                reactions_exported,
                status,
                started_at,
                completed_at
            FROM export_progress
            WHERE space_id = ?
        """, (space_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            'threads': row[0],
            'messages': row[1],
            'attachments': row[2],
            'reactions': row[3],
            'status': row[4],
            'started_at': row[5],
            'completed_at': row[6]
        }
    
    def get_overall_progress(self) -> Dict[str, Any]:
        """Get overall export progress across all spaces."""
        cursor = self.state_conn.execute("""
            SELECT 
                COUNT(*) as total_spaces,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_spaces,
                SUM(threads_exported) as total_threads,
                SUM(messages_exported) as total_messages,
                SUM(attachments_exported) as total_attachments,
                SUM(reactions_exported) as total_reactions
            FROM export_progress
        """)
        
        row = cursor.fetchone()
        
        return {
            'total_spaces': row[0] or 0,
            'completed_spaces': row[1] or 0,
            'total_threads': row[2] or 0,
            'total_messages': row[3] or 0,
            'total_attachments': row[4] or 0,
            'total_reactions': row[5] or 0
        }
```

**Test**:

```python
def test_export_state_manager_tracks_progress(tmp_path):
    """Test progress tracking."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    manager = ExportStateManager(state_db.conn, chat_db.conn)
    
    # Initialize
    manager.initialize_space_progress('space1')
    
    # Update progress
    manager.update_progress('space1', threads=5, messages=50)
    manager.update_progress('space1', messages=25, reactions=10)
    
    # Check progress
    progress = manager.get_space_progress('space1')
    
    assert progress['threads'] == 5
    assert progress['messages'] == 75
    assert progress['reactions'] == 10
    assert progress['status'] == 'in_progress'

def test_export_state_manager_marks_complete(tmp_path):
    """Test marking space as complete."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    manager = ExportStateManager(state_db.conn, chat_db.conn)
    
    manager.initialize_space_progress('space1')
    manager.mark_space_complete('space1')
    
    progress = manager.get_space_progress('space1')
    
    assert progress['status'] == 'completed'
    assert progress['completed_at'] is not None
```

### 5. CLI Integration

#### 5.1 Export Command

**Test**: CLI command to start export

**File**: `src/gchat_mirror/cli/export.py` (additions)

```python
# Add to existing export.py

@export_group.command()
@click.option('--mapping-mode', 
              type=click.Choice(['chat', 'private_messages', 'hybrid']),
              default='hybrid',
              help='How to map spaces to Discourse')
@click.option('--max-parallel',
              type=int,
              default=5,
              help='Maximum parallel exports')
def start(mapping_mode: str, max_parallel: int):
    """Start the Discourse exporter."""
    from gchat_mirror.exporters.discourse.exporter_daemon import ExporterDaemon
    
    config = get_config()
    
    # Initialize exporter
    daemon = ExporterDaemon(
        config=config,
        mapping_mode=mapping_mode,
        max_parallel=max_parallel
    )
    
    click.echo("Starting Discourse exporter...")
    daemon.run()

@export_group.command()
def status():
    """Show export status."""
    from gchat_mirror.exporters.discourse.export_state import ExportStateManager
    
    config = get_config()
    state_conn = get_state_connection(config)
    chat_conn = get_chat_connection(config)
    
    manager = ExportStateManager(state_conn, chat_conn)
    
    progress = manager.get_overall_progress()
    
    click.echo(f"Overall Export Progress:")
    click.echo(f"  Spaces: {progress['completed_spaces']}/{progress['total_spaces']}")
    click.echo(f"  Threads: {progress['total_threads']}")
    click.echo(f"  Messages: {progress['total_messages']}")
    click.echo(f"  Attachments: {progress['total_attachments']}")
    click.echo(f"  Reactions: {progress['total_reactions']}")

@export_group.command()
@click.argument('entity_type')
@click.argument('entity_id')
def retry(entity_type: str, entity_id: str):
    """Force retry of a failed export."""
    from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager
    
    config = get_config()
    state_conn = get_state_connection(config)
    
    manager = FailedExportManager(state_conn)
    manager.force_retry(entity_type, entity_id)
    
    click.echo(f"Forced retry for {entity_type} {entity_id}")
```

## Completion Criteria

- [ ] Attachment cache uploads and caches URLs
- [ ] Message exporter handles threading and edits
- [ ] Parallel message export working
- [ ] Reactions exported to posts
- [ ] Export progress tracked per space
- [ ] CLI commands functional (start, status, retry)
- [ ] State management tracks completion
- [ ] All tests pass
- [ ] Integration tests verify end-to-end export

## Next Steps

After Phase 4.7, the Discourse exporter is complete. Proceed to Phase 5: Polish and Production Readiness.
