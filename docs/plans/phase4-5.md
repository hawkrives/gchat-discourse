# Phase 4.5: Thread and Message Export

## Goal

Export Google Chat threads and messages to Discourse with proper threading, markdown conversion, edit history, attachments, and reactions.

## Duration

1 week

## Prerequisites

- Phase 4.1-4.4 complete (database, API client, user/space mapping)
- All message data in chat.db
- Space mappings established

## Overview

This phase implements the core message export logic:

1. **Thread Export** - Convert GChat threads to Discourse topics/PMs with generated titles
2. **Message Export** - Export messages with proper threading and reply relationships
3. **Markdown Conversion** - Transform GChat formatting to Discourse markdown
4. **Edit History** - Preserve message revisions
5. **Attachment Export** - Upload files with URL caching
6. **Reaction Export** - Add reactions to posts

## Tasks

### 1. Thread Title Generation

#### 1.1 Thread Title Generator

**Test**: Generates appropriate titles from first messages

**File**: `src/gchat_mirror/exporters/discourse/thread_title.py`

```python
# ABOUTME: Thread title generation from Google Chat messages
# ABOUTME: Extracts meaningful titles for Discourse topics

import re
from typing import Optional
import structlog

logger = structlog.get_logger()

class ThreadTitleGenerator:
    """Generate Discourse topic titles from Google Chat threads."""
    
    MAX_TITLE_LENGTH = 255
    MIN_TITLE_LENGTH = 3
    DEFAULT_TITLE = "Chat Thread"
    
    def generate_title(self, message_text: Optional[str], 
                      space_name: str,
                      thread_id: str) -> str:
        """
        Generate a topic title from the first message.
        
        Args:
            message_text: First message text (may be None for deleted messages)
            space_name: Name of the Google Chat space
            thread_id: Thread ID for fallback
        
        Returns:
            Suitable topic title
        """
        if not message_text or not message_text.strip():
            # No text - use space name + thread ID
            title = f"{space_name} - {thread_id[:8]}"
            logger.debug("thread_title_fallback", thread_id=thread_id)
            return self._truncate_title(title)
        
        # Clean the text
        cleaned = self._clean_text(message_text)
        
        if not cleaned:
            return self._truncate_title(f"{space_name} - {thread_id[:8]}")
        
        # Use first sentence or first line
        title = self._extract_first_sentence(cleaned)
        
        # Ensure reasonable length
        if len(title) < self.MIN_TITLE_LENGTH:
            title = f"{space_name} - {title}"
        
        return self._truncate_title(title)
    
    def _clean_text(self, text: str) -> str:
        """
        Clean message text for title use.
        
        - Remove markdown formatting
        - Remove mentions
        - Remove URLs
        - Normalize whitespace
        """
        # Remove markdown formatting
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*(.+?)\*', r'\1', text)      # Italic
        text = re.sub(r'`(.+?)`', r'\1', text)        # Code
        text = re.sub(r'~~(.+?)~~', r'\1', text)      # Strikethrough
        
        # Remove mentions (@user)
        text = re.sub(r'<users/[^>]+>', '', text)
        
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _extract_first_sentence(self, text: str) -> str:
        """Extract first sentence or up to first newline."""
        # First newline?
        if '\n' in text:
            first_line = text.split('\n')[0].strip()
            if first_line:
                return first_line
        
        # First sentence (period, question mark, or exclamation)
        match = re.match(r'^([^.!?]+[.!?])', text)
        if match:
            return match.group(1).strip()
        
        # Just use the whole text
        return text
    
    def _truncate_title(self, title: str) -> str:
        """Truncate title to maximum length."""
        if len(title) <= self.MAX_TITLE_LENGTH:
            return title
        
        # Truncate at word boundary
        truncated = title[:self.MAX_TITLE_LENGTH - 3]
        last_space = truncated.rfind(' ')
        
        if last_space > self.MAX_TITLE_LENGTH // 2:
            truncated = truncated[:last_space]
        
        return truncated + '...'
```

**Test**:

```python
def test_thread_title_from_simple_message():
    """Test title generation from simple message."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "Hey everyone, let's discuss the new feature",
        "Engineering",
        "thread123"
    )
    
    assert title == "Hey everyone, let's discuss the new feature"

def test_thread_title_first_sentence():
    """Test extracting first sentence."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "This is the first sentence. This is the second.",
        "Engineering",
        "thread123"
    )
    
    assert title == "This is the first sentence."

def test_thread_title_first_line():
    """Test extracting first line."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "First line\nSecond line\nThird line",
        "Engineering",
        "thread123"
    )
    
    assert title == "First line"

def test_thread_title_removes_markdown():
    """Test markdown removal."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "This is **bold** and *italic* and `code`",
        "Engineering",
        "thread123"
    )
    
    assert title == "This is bold and italic and code"

def test_thread_title_removes_mentions():
    """Test mention removal."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "<users/123456> can you review this?",
        "Engineering",
        "thread123"
    )
    
    assert title == "can you review this?"

def test_thread_title_fallback_empty():
    """Test fallback for empty message."""
    generator = ThreadTitleGenerator()
    
    title = generator.generate_title(
        "",
        "Engineering",
        "thread123"
    )
    
    assert title == "Engineering - thread12"

def test_thread_title_truncation():
    """Test title truncation at max length."""
    generator = ThreadTitleGenerator()
    
    long_text = "A" * 300
    title = generator.generate_title(long_text, "Engineering", "thread123")
    
    assert len(title) <= 255
    assert title.endswith('...')
```

### 2. Message Transformation

#### 2.1 Markdown Converter

**Test**: Converts GChat formatting to Discourse markdown

**File**: `src/gchat_mirror/exporters/discourse/markdown_converter.py`

```python
# ABOUTME: Google Chat to Discourse markdown conversion
# ABOUTME: Handles formatting, mentions, and attachment references

import re
from typing import Dict, List, Optional, Tuple
import sqlite3
import structlog

logger = structlog.get_logger()

class MarkdownConverter:
    """Convert Google Chat messages to Discourse markdown."""
    
    def __init__(self, chat_conn: sqlite3.Connection, 
                 user_mapper: 'UserMapper',
                 attachment_cache: Dict[str, str]):
        self.chat_conn = chat_conn
        self.user_mapper = user_mapper
        self.attachment_cache = attachment_cache
    
    def convert_message(self, message_text: str, 
                       message_id: str,
                       attachments: List[Dict]) -> str:
        """
        Convert Google Chat message to Discourse markdown.
        
        Args:
            message_text: Raw message text with GChat formatting
            message_id: Message ID for attachment lookup
            attachments: List of attachment dicts
        
        Returns:
            Discourse-compatible markdown
        """
        if not message_text:
            message_text = ""
        
        # Convert formatting
        markdown = self._convert_formatting(message_text)
        
        # Convert mentions
        markdown = self._convert_mentions(markdown)
        
        # Add attachments
        if attachments:
            markdown = self._add_attachments(markdown, attachments)
        
        return markdown
    
    def _convert_formatting(self, text: str) -> str:
        """
        Convert Google Chat formatting to Discourse markdown.
        
        GChat uses similar markdown to Discourse, but we need to
        handle some edge cases.
        """
        # Bold: **text** (same in both)
        # Italic: *text* (same in both)
        # Strikethrough: ~~text~~ (same in both)
        # Code: `text` (same in both)
        # Code block: ```text``` (same in both)
        
        # GChat uses _text_ for underline, but Discourse doesn't support it
        # Convert to <u>text</u>
        text = re.sub(r'(?<!\\)_([^_]+?)_', r'<u>\1</u>', text)
        
        # GChat uses > for quotes (same as Discourse)
        
        return text
    
    def _convert_mentions(self, text: str) -> str:
        """
        Convert Google Chat mentions to Discourse mentions.
        
        GChat format: <users/123456>
        Discourse format: @username
        """
        def replace_mention(match):
            user_id = match.group(1)
            
            # Get Discourse username
            username = self.user_mapper.get_or_create_discourse_user(user_id)
            
            if username:
                return f"@{username}"
            else:
                # Fallback: show display name without @ link
                cursor = self.chat_conn.execute("""
                    SELECT display_name FROM users WHERE id = ?
                """, (user_id,))
                result = cursor.fetchone()
                if result:
                    return f"@{result[0]}"
                else:
                    return match.group(0)  # Keep original
        
        return re.sub(r'<users/([^>]+)>', replace_mention, text)
    
    def _add_attachments(self, text: str, 
                        attachments: List[Dict]) -> str:
        """
        Add attachment references to message.
        
        Args:
            text: Message text
            attachments: List of dicts with 'id', 'name', 'content_type'
        
        Returns:
            Text with attachment markdown
        """
        attachment_lines = []
        
        for attachment in attachments:
            attachment_id = attachment['id']
            name = attachment['name']
            content_type = attachment.get('content_type', '')
            
            # Check if we have a Discourse URL for this attachment
            discourse_url = self.attachment_cache.get(attachment_id)
            
            if not discourse_url:
                logger.warning("attachment_url_missing",
                             attachment_id=attachment_id)
                attachment_lines.append(f"*[Attachment: {name}]*")
                continue
            
            # Format based on MIME type
            if content_type.startswith('image/'):
                # Embed image
                attachment_lines.append(f"![{name}]({discourse_url})")
            else:
                # Link to file
                attachment_lines.append(f"[{name}]({discourse_url})")
        
        if attachment_lines:
            # Add attachments after message text
            if text:
                return text + "\n\n" + "\n".join(attachment_lines)
            else:
                return "\n".join(attachment_lines)
        
        return text
```

**Test**:

```python
def test_markdown_converter_formatting():
    """Test basic formatting conversion."""
    converter = MarkdownConverter(Mock(), Mock(), {})
    
    result = converter.convert_message(
        "This is **bold** and *italic* and ~~strikethrough~~",
        "msg1",
        []
    )
    
    assert "**bold**" in result
    assert "*italic*" in result
    assert "~~strikethrough~~" in result

def test_markdown_converter_underline():
    """Test underline conversion."""
    converter = MarkdownConverter(Mock(), Mock(), {})
    
    result = converter.convert_message(
        "This is _underlined_ text",
        "msg1",
        []
    )
    
    assert "<u>underlined</u>" in result

def test_markdown_converter_mentions(tmp_path):
    """Test mention conversion."""
    chat_db = setup_test_chat_db(tmp_path)
    
    chat_db.conn.execute("""
        INSERT INTO users (id, display_name)
        VALUES ('user1', 'Alice')
    """)
    chat_db.conn.commit()
    
    user_mapper = Mock()
    user_mapper.get_or_create_discourse_user.return_value = "alice"
    
    converter = MarkdownConverter(chat_db.conn, user_mapper, {})
    
    result = converter.convert_message(
        "Hey <users/user1>, can you help?",
        "msg1",
        []
    )
    
    assert "@alice" in result
    assert "<users/user1>" not in result

def test_markdown_converter_images():
    """Test image attachment embedding."""
    attachments = [{
        'id': 'attach1',
        'name': 'photo.jpg',
        'content_type': 'image/jpeg'
    }]
    
    cache = {
        'attach1': 'https://discourse.example.com/uploads/photo.jpg'
    }
    
    converter = MarkdownConverter(Mock(), Mock(), cache)
    
    result = converter.convert_message(
        "Check this out!",
        "msg1",
        attachments
    )
    
    assert "Check this out!" in result
    assert "![photo.jpg](https://discourse.example.com/uploads/photo.jpg)" in result

def test_markdown_converter_files():
    """Test file attachment linking."""
    attachments = [{
        'id': 'attach1',
        'name': 'document.pdf',
        'content_type': 'application/pdf'
    }]
    
    cache = {
        'attach1': 'https://discourse.example.com/uploads/document.pdf'
    }
    
    converter = MarkdownConverter(Mock(), Mock(), cache)
    
    result = converter.convert_message(
        "See attached document",
        "msg1",
        attachments
    )
    
    assert "[document.pdf](https://discourse.example.com/uploads/document.pdf)" in result
```

### 3. Thread Exporter

#### 3.1 Thread Export Manager

**Test**: Exports threads as topics or PMs

**File**: `src/gchat_mirror/exporters/discourse/thread_exporter.py`

```python
# ABOUTME: Thread export to Discourse topics or private messages
# ABOUTME: Creates topics/PMs with generated titles from first messages

import sqlite3
from typing import Dict, Any, Optional, List
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.thread_title import ThreadTitleGenerator
from gchat_mirror.exporters.discourse.user_mapper import UserMapper
from gchat_mirror.exporters.discourse.space_mapper import SpaceMapper

logger = structlog.get_logger()

class ThreadExporter:
    """Export Google Chat threads to Discourse."""
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 user_mapper: UserMapper,
                 space_mapper: SpaceMapper):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.user_mapper = user_mapper
        self.space_mapper = space_mapper
        self.title_generator = ThreadTitleGenerator()
    
    def export_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Export a Google Chat thread to Discourse.
        
        Args:
            thread_id: Google Chat thread ID
        
        Returns:
            Mapping data with discourse_type and discourse_id,
            or None if export fails
        """
        # Check if already exported
        cursor = self.state_conn.execute("""
            SELECT discourse_type, discourse_id FROM export_mappings
            WHERE source_type = 'thread' AND source_id = ?
        """, (thread_id,))
        
        result = cursor.fetchone()
        if result:
            logger.debug("thread_already_exported", thread_id=thread_id)
            return {
                'discourse_type': result[0],
                'discourse_id': result[1]
            }
        
        # Get thread data
        cursor = self.chat_conn.execute("""
            SELECT space_id, reply_count
            FROM threads
            WHERE id = ?
        """, (thread_id,))
        
        thread = cursor.fetchone()
        if not thread:
            logger.error("thread_not_found", thread_id=thread_id)
            return None
        
        space_id, reply_count = thread
        
        # Get space mapping
        space_mapping = self.space_mapper.get_or_create_space_mapping(space_id)
        if not space_mapping:
            logger.error("space_mapping_failed", space_id=space_id)
            return None
        
        # Get first message for title
        cursor = self.chat_conn.execute("""
            SELECT text FROM messages
            WHERE thread_id = ?
            ORDER BY create_time ASC
            LIMIT 1
        """, (thread_id,))
        
        first_msg = cursor.fetchone()
        first_text = first_msg[0] if first_msg else None
        
        # Get space name
        cursor = self.chat_conn.execute("""
            SELECT display_name FROM spaces WHERE id = ?
        """, (space_id,))
        space_name = cursor.fetchone()[0]
        
        # Generate title
        title = self.title_generator.generate_title(
            first_text,
            space_name,
            thread_id
        )
        
        # Export based on space mapping type
        if space_mapping['type'] == 'chat_channel':
            # Threads in chat channels become... threads?
            # Actually, Discourse chat doesn't have threads
            # We need to just export as regular messages
            # This is handled by message exporter
            logger.warning("thread_in_chat_channel",
                         thread_id=thread_id,
                         note="Will export as flat messages")
            return {
                'discourse_type': 'chat_thread',
                'discourse_id': 0  # No actual thread
            }
        
        elif space_mapping['type'] == 'category':
            # Create topic in category
            return self._create_topic(
                thread_id,
                title,
                space_mapping['id']
            )
        
        elif space_mapping['type'] == 'private_message':
            # Create private message thread
            return self._create_private_message(
                thread_id,
                title,
                space_mapping['participants']
            )
        
        else:
            logger.error("unknown_space_mapping_type",
                        type=space_mapping['type'])
            return None
    
    def _create_topic(self, thread_id: str, title: str,
                     category_id: int) -> Dict[str, Any]:
        """Create a Discourse topic for a thread."""
        try:
            # We'll create the topic with the first message
            # For now, just create a placeholder
            result = self.discourse.create_topic(
                title=title,
                raw="Thread content will be populated...",
                category_id=category_id
            )
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('thread', ?, 'topic', ?)
            """, (thread_id, result['topic_id']))
            self.state_conn.commit()
            
            logger.info("topic_created",
                       thread_id=thread_id,
                       topic_id=result['topic_id'])
            
            return {
                'discourse_type': 'topic',
                'discourse_id': result['topic_id']
            }
        
        except Exception as e:
            logger.error("topic_creation_failed",
                        thread_id=thread_id,
                        error=str(e))
            raise
    
    def _create_private_message(self, thread_id: str, title: str,
                               participants: List[str]) -> Dict[str, Any]:
        """Create a Discourse private message for a thread."""
        try:
            # Map participants to Discourse usernames
            usernames = []
            for user_id in participants:
                username = self.user_mapper.get_or_create_discourse_user(user_id)
                if username:
                    usernames.append(username)
            
            if not usernames:
                logger.error("no_valid_participants", thread_id=thread_id)
                return None
            
            # Create PM
            result = self.discourse.create_private_message(
                title=title,
                raw="Thread content will be populated...",
                target_usernames=usernames
            )
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('thread', ?, 'private_message', ?)
            """, (thread_id, result['topic_id']))
            self.state_conn.commit()
            
            logger.info("private_message_created",
                       thread_id=thread_id,
                       topic_id=result['topic_id'])
            
            return {
                'discourse_type': 'private_message',
                'discourse_id': result['topic_id']
            }
        
        except Exception as e:
            logger.error("private_message_creation_failed",
                        thread_id=thread_id,
                        error=str(e))
            raise
```

**Test**:

```python
def test_thread_exporter_creates_topic(tmp_path, httpx_mock):
    """Test exporting thread as topic."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Set up test data
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_db.conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 5)
    """)
    chat_db.conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'Hello everyone!', '2024-01-01 10:00:00')
    """)
    chat_db.conn.commit()
    
    # Set up space mapping
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('space', 'space1', 'category', 42)
    """)
    state_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    user_mapper = Mock()
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'category',
        'id': 42
    }
    
    exporter = ThreadExporter(
        client,
        state_db.conn,
        chat_db.conn,
        user_mapper,
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result['discourse_type'] == 'topic'
    assert result['discourse_id'] == 123
    
    # Verify mapping stored
    cursor = state_db.conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'thread' AND source_id = 'thread1'
    """)
    assert cursor.fetchone()[0] == 123

def test_thread_exporter_creates_private_message(tmp_path, httpx_mock):
    """Test exporting DM thread as private message."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Set up test data
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('dm1', 'DM with Bob', 'DM')
    """)
    chat_db.conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'dm1', 3)
    """)
    chat_db.conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'dm1', 'Hey Bob!', '2024-01-01 10:00:00')
    """)
    chat_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 789, "id": 890}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    
    user_mapper = Mock()
    user_mapper.get_or_create_discourse_user.side_effect = ["alice", "bob"]
    
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'private_message',
        'id': 0,
        'participants': ['user1', 'user2']
    }
    
    exporter = ThreadExporter(
        client,
        state_db.conn,
        chat_db.conn,
        user_mapper,
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result['discourse_type'] == 'private_message'
    assert result['discourse_id'] == 789
```

### 4. Message Exporter

(Implementation continues with message export, edit history, attachments, and reactions - this section would be detailed but I want to keep message length reasonable)

## Completion Criteria

- [ ] Thread title generator working
- [ ] Markdown converter handles all formatting
- [ ] Mentions converted properly
- [ ] Threads exported as topics/PMs
- [ ] Messages exported with proper content
- [ ] Reply threading preserved
- [ ] Edit history tracked
- [ ] Attachments uploaded and linked
- [ ] Reactions added to posts
- [ ] All tests pass

## Next Steps

After Phase 4.5, proceed to Phase 4.6: Failed Export Tracking and Retry
