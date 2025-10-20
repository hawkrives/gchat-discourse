# Phase 4.4: Space to Discourse Mapping

## Goal

Map Google Chat spaces to appropriate Discourse structures based on configuration mode.

## Duration

1 day

## Prerequisites

- Phase 4.1 complete (database schema)
- Phase 4.2 complete (Discourse API client)
- Phase 4.3 complete (user management)

## Overview

The space mapper creates the appropriate Discourse entity for each Google Chat space based on the mapping mode:

1. **chat mode** - All spaces become Discourse chat channels
2. **private_messages mode** - DMs become private messages, regular spaces become categories
3. **hybrid mode** (default) - DMs become private messages, regular spaces become chat channels

## Tasks

### 1. Space Mapper Implementation

#### 1.1 Space Mapping with Mode Support

**Test**: Maps spaces based on configuration mode

**File**: `src/gchat_mirror/exporters/discourse/space_mapper.py`

```python
# ABOUTME: Space mapping for different Discourse export modes
# ABOUTME: Handles chat/private_messages/hybrid mapping strategies

import sqlite3
from typing import Dict, Any, Optional, Literal
import structlog

from gchat_mirror.exporters/discourse.discourse_client import DiscourseClient

logger = structlog.get_logger()

MappingMode = Literal["chat", "private_messages", "hybrid"]

class SpaceMapper:
    """Map Google Chat spaces to Discourse structures."""
    
    def __init__(self, discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 mapping_mode: MappingMode):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.mapping_mode = mapping_mode
    
    def get_or_create_space_mapping(self, space_id: str) -> Dict[str, Any]:
        """
        Get or create Discourse mapping for a Google Chat space.
        
        Returns dict with:
        - type: 'chat_channel', 'category', or 'private_message'
        - id: Discourse entity ID
        - name: Discourse entity name/username
        """
        # Check existing mapping
        cursor = self.state_conn.execute("""
            SELECT discourse_type, discourse_id FROM export_mappings
            WHERE source_type = 'space' AND source_id = ?
        """, (space_id,))
        
        result = cursor.fetchone()
        if result:
            discourse_type, discourse_id = result
            return {
                'type': discourse_type,
                'id': discourse_id
            }
        
        # Get space data
        cursor = self.chat_conn.execute("""
            SELECT display_name, space_type, threaded 
            FROM spaces WHERE id = ?
        """, (space_id,))
        
        space = cursor.fetchone()
        if not space:
            logger.error("space_not_found", space_id=space_id)
            return None
        
        display_name, space_type, threaded = space
        
        # Determine mapping based on mode and space type
        is_dm = space_type == "DM"
        
        if self.mapping_mode == "chat":
            # All spaces become chat channels
            return self._create_chat_channel(space_id, display_name)
        
        elif self.mapping_mode == "private_messages":
            if is_dm:
                # DMs become private messages
                return self._setup_private_message(space_id)
            else:
                # Regular spaces become categories
                return self._create_category(space_id, display_name)
        
        else:  # hybrid
            if is_dm:
                # DMs become private messages
                return self._setup_private_message(space_id)
            else:
                # Regular spaces become chat channels
                return self._create_chat_channel(space_id, display_name)
    
    def _create_chat_channel(self, space_id: str, display_name: str) -> Dict[str, Any]:
        """Create a Discourse chat channel."""
        try:
            channel = self.discourse.create_chat_channel(
                name=display_name,
                description=f"Mirrored from Google Chat space {space_id}"
            )
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('space', ?, 'chat_channel', ?)
            """, (space_id, channel['id']))
            self.state_conn.commit()
            
            logger.info("chat_channel_created",
                       space_id=space_id,
                       channel_id=channel['id'])
            
            return {
                'type': 'chat_channel',
                'id': channel['id'],
                'name': display_name
            }
        
        except Exception as e:
            logger.error("chat_channel_creation_failed",
                        space_id=space_id,
                        error=str(e))
            raise
    
    def _create_category(self, space_id: str, display_name: str) -> Dict[str, Any]:
        """Create a Discourse category."""
        try:
            category = self.discourse.create_category(
                name=display_name,
                color="0088CC"
            )
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('space', ?, 'category', ?)
            """, (space_id, category['id']))
            self.state_conn.commit()
            
            logger.info("category_created",
                       space_id=space_id,
                       category_id=category['id'])
            
            return {
                'type': 'category',
                'id': category['id'],
                'name': display_name
            }
        
        except Exception as e:
            logger.error("category_creation_failed",
                        space_id=space_id,
                        error=str(e))
            raise
    
    def _setup_private_message(self, space_id: str) -> Dict[str, Any]:
        """
        Set up private message mapping for a DM space.
        
        For DMs, we don't create anything upfront - the mapping
        just indicates that threads in this space should become PMs.
        """
        # Get participants
        cursor = self.chat_conn.execute("""
            SELECT user_id FROM memberships WHERE space_id = ?
        """, (space_id,))
        
        participants = [row[0] for row in cursor.fetchall()]
        
        # Store mapping with participant list
        self.state_conn.execute("""
            INSERT INTO export_mappings
            (source_type, source_id, discourse_type, discourse_id)
            VALUES ('space', ?, 'private_message', ?)
        """, (space_id, ','.join(participants)))
        self.state_conn.commit()
        
        logger.info("private_message_setup",
                   space_id=space_id,
                   participants=len(participants))
        
        return {
            'type': 'private_message',
            'id': 0,  # No Discourse ID yet
            'participants': participants
        }
```

**Test**:

```python
def test_space_mapper_chat_mode(tmp_path, httpx_mock):
    """Test space mapping in chat mode."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add space
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/chat/api/channels.json",
        method="POST",
        json={"channel": {"id": 42, "name": "Engineering"}}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    mapper = SpaceMapper(client, state_db.conn, chat_db.conn, "chat")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42

def test_space_mapper_private_messages_mode_regular_space(tmp_path, httpx_mock):
    """Test regular space mapping in private_messages mode."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add regular space
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/categories.json",
        method="POST",
        json={"category": {"id": 99, "name": "Engineering"}}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    mapper = SpaceMapper(client, state_db.conn, chat_db.conn, "private_messages")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result['type'] == 'category'
    assert result['id'] == 99

def test_space_mapper_hybrid_mode_dm(tmp_path):
    """Test DM mapping in hybrid mode."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add DM space
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('dm1', 'DM with Bob', 'DM')
    """)
    chat_db.conn.execute("""
        INSERT INTO memberships (space_id, user_id)
        VALUES ('dm1', 'user1'), ('dm1', 'user2')
    """)
    chat_db.conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_db.conn, chat_db.conn, "hybrid")
    
    result = mapper.get_or_create_space_mapping('dm1')
    
    assert result['type'] == 'private_message'
    assert len(result['participants']) == 2

def test_space_mapper_hybrid_mode_regular_space(tmp_path, httpx_mock):
    """Test regular space mapping in hybrid mode."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add regular space
    chat_db.conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/chat/api/channels.json",
        method="POST",
        json={"channel": {"id": 42, "name": "Engineering"}}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    mapper = SpaceMapper(client, state_db.conn, chat_db.conn, "hybrid")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42

def test_space_mapper_caches_mappings(tmp_path, httpx_mock):
    """Test that mappings are cached and reused."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Pre-populate mapping
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('space', 'space1', 'chat_channel', 42)
    """)
    state_db.conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_db.conn, chat_db.conn, "chat")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42
    # Should not call Discourse API
    assert not client.create_chat_channel.called
```

## Mapping Modes

### Chat Mode
All spaces (including DMs) become Discourse chat channels.

**Use when**: You want everything in Discourse Chat plugin

**Mappings**:
- Regular space → Chat channel
- DM → Chat channel

### Private Messages Mode
DMs become private messages, regular spaces become categories with topics.

**Use when**: You want structured forum-style discussions

**Mappings**:
- Regular space → Category
- DM → Private message
- Thread → Topic in category

### Hybrid Mode (Default)
DMs become private messages, regular spaces become chat channels.

**Use when**: You want chat-like experience for spaces, but proper PMs for DMs

**Mappings**:
- Regular space → Chat channel
- DM → Private message

## Space Mapping Storage

The `export_mappings` table stores space mappings:

```sql
INSERT INTO export_mappings 
(source_type, source_id, discourse_type, discourse_id)
VALUES ('space', 'spaces/abc123', 'chat_channel', 42)
```

For private messages, `discourse_id` stores the participant list:
```sql
VALUES ('space', 'spaces/dm456', 'private_message', 'user1,user2')
```

## Completion Criteria

- [ ] All three mapping modes implemented
- [ ] Chat channels created properly
- [ ] Categories created properly
- [ ] Private message setup working
- [ ] Mappings cached in database
- [ ] Existing mappings reused
- [ ] All tests pass

## Next Steps

After Phase 4.4, proceed to Phase 4.5: Thread and Message Export
