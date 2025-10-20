# Phase 4: Discourse Exporter - Detailed Specification

## Goal

Export all Google Chat data to Discourse with configurable mapping, preserving complete message history, attachments, and reactions.

## Duration

3-4 weeks

## Prerequisites

- Phase 1, 2, and 3 complete
- Discourse instance available with admin API key
- All data types stored in chat.db

## Overview

The Discourse exporter runs as a standalone process that watches the notification queue and exports data to Discourse. It supports three mapping modes:

1. **chat** - Spaces become Discourse chat channels
2. **private_messages** - DMs become private messages, spaces become topics
3. **hybrid** - DMs become private messages, spaces become chat channels

## Tasks

### 1. Exporter Database Schema

#### 1.1 Create Exporter State Database

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

### 2. Discourse API Client

#### 2.1 Core API Client

**Test**: Can interact with Discourse API

**File**: `src/gchat_mirror/exporters/discourse/discourse_client.py`

```python
# ABOUTME: Discourse API client for creating and updating content
# ABOUTME: Handles authentication, rate limiting, and error handling

import httpx
from typing import Dict, Any, List, Optional
import structlog
from datetime import datetime

logger = structlog.get_logger()

class DiscourseClient:
    """Client for Discourse API."""
    
    def __init__(self, base_url: str, api_key: str, api_username: str = "system"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.api_username = api_username
        
        self.client = httpx.Client(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=30.0
        )
        
        logger.info("discourse_client_initialized", url=base_url)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API headers."""
        return {
            "Api-Key": self.api_key,
            "Api-Username": self.api_username,
            "Content-Type": "application/json"
        }
    
    def _handle_rate_limit(self, response: httpx.Response):
        """Handle rate limit response."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            logger.warning("discourse_rate_limited", retry_after=retry_after)
            raise DiscourseRateLimitError(int(retry_after))
    
    # Categories
    
    def create_category(self, name: str, color: str = "0088CC",
                       text_color: str = "FFFFFF",
                       parent_category_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Create a Discourse category.
        
        Args:
            name: Category name
            color: Hex color (without #)
            text_color: Text hex color (without #)
            parent_category_id: Parent category ID if subcategory
        
        Returns:
            Category data including id
        """
        data = {
            "name": name,
            "color": color,
            "text_color": text_color
        }
        
        if parent_category_id:
            data["parent_category_id"] = parent_category_id
        
        response = self.client.post("/categories.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        category = response.json()["category"]
        logger.info("category_created", name=name, id=category["id"])
        
        return category
    
    def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        """Get category by ID."""
        try:
            response = self.client.get(f"/c/{category_id}/show.json")
            response.raise_for_status()
            return response.json()["category"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    # Topics
    
    def create_topic(self, title: str, raw: str, category_id: int,
                     created_at: Optional[str] = None,
                     tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a Discourse topic (thread).
        
        Args:
            title: Topic title
            raw: First post content (markdown)
            category_id: Category to post in
            created_at: ISO timestamp for post backdating
            tags: List of tag names
        
        Returns:
            Topic data including id and post id
        """
        data = {
            "title": title,
            "raw": raw,
            "category": category_id
        }
        
        if created_at:
            data["created_at"] = created_at
        
        if tags:
            data["tags"] = tags
        
        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        result = response.json()
        logger.info("topic_created", title=title, topic_id=result["topic_id"])
        
        return result
    
    def get_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get topic by ID."""
        try:
            response = self.client.get(f"/t/{topic_id}.json")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    # Posts
    
    def create_post(self, topic_id: int, raw: str,
                   created_at: Optional[str] = None,
                   reply_to_post_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Create a post in an existing topic.
        
        Args:
            topic_id: Topic to post in
            raw: Post content (markdown)
            created_at: ISO timestamp for backdating
            reply_to_post_number: Post number this is replying to
        
        Returns:
            Post data including id
        """
        data = {
            "topic_id": topic_id,
            "raw": raw
        }
        
        if created_at:
            data["created_at"] = created_at
        
        if reply_to_post_number:
            data["reply_to_post_number"] = reply_to_post_number
        
        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        post = response.json()
        logger.info("post_created", topic_id=topic_id, post_id=post["id"])
        
        return post
    
    def update_post(self, post_id: int, raw: str) -> Dict[str, Any]:
        """Update a post's content."""
        data = {"post": {"raw": raw}}
        
        response = self.client.put(f"/posts/{post_id}.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        post = response.json()["post"]
        logger.info("post_updated", post_id=post_id)
        
        return post
    
    # Uploads
    
    def upload_file(self, filename: str, file_data: bytes,
                   content_type: str = "application/octet-stream") -> Dict[str, Any]:
        """
        Upload a file to Discourse.
        
        Args:
            filename: Name of file
            file_data: File bytes
            content_type: MIME type
        
        Returns:
            Upload data including URL
        """
        files = {
            "file": (filename, file_data, content_type)
        }
        
        # Uploads use different headers
        headers = {
            "Api-Key": self.api_key,
            "Api-Username": self.api_username
        }
        
        response = self.client.post(
            "/uploads.json",
            files=files,
            headers=headers,
            params={"type": "composer"}
        )
        
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        upload = response.json()
        logger.info("file_uploaded", filename=filename, 
                   url=upload.get("url", upload.get("short_url")))
        
        return upload
    
    # Users
    
    def create_user(self, email: str, username: str, name: str,
                   password: str = None) -> Dict[str, Any]:
        """
        Create a Discourse user.
        
        Args:
            email: User email
            username: Username
            name: Display name
            password: Password (auto-generated if None)
        
        Returns:
            User data including id
        """
        import secrets
        
        data = {
            "email": email,
            "username": username,
            "name": name,
            "password": password or secrets.token_urlsafe(32),
            "active": True
        }
        
        response = self.client.post("/users.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        user = response.json()
        logger.info("user_created", username=username, user_id=user.get("user_id"))
        
        return user
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        try:
            response = self.client.get(f"/users/{username}.json")
            response.raise_for_status()
            return response.json()["user"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
    
    # Chat (Discourse Chat plugin)
    
    def create_chat_channel(self, name: str, description: str = "",
                           auto_join_users: bool = True) -> Dict[str, Any]:
        """
        Create a chat channel (requires Discourse Chat plugin).
        
        Args:
            name: Channel name
            description: Channel description
            auto_join_users: Whether users auto-join
        
        Returns:
            Channel data including id
        """
        data = {
            "channel": {
                "name": name,
                "description": description,
                "auto_join_users": auto_join_users
            }
        }
        
        response = self.client.post("/chat/api/channels.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        channel = response.json()["channel"]
        logger.info("chat_channel_created", name=name, id=channel["id"])
        
        return channel
    
    def send_chat_message(self, channel_id: int, message: str,
                         created_at: Optional[str] = None) -> Dict[str, Any]:
        """Send a message to a chat channel."""
        data = {
            "message": message,
            "channel_id": channel_id
        }
        
        if created_at:
            data["created_at"] = created_at
        
        response = self.client.post(
            f"/chat/api/channels/{channel_id}/messages.json",
            json=data
        )
        
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        msg = response.json()["message"]
        logger.info("chat_message_sent", channel_id=channel_id, 
                   message_id=msg["id"])
        
        return msg
    
    # Private Messages
    
    def create_private_message(self, title: str, raw: str,
                              target_usernames: List[str],
                              created_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a private message.
        
        Args:
            title: PM title
            raw: First message content
            target_usernames: List of recipient usernames
            created_at: ISO timestamp for backdating
        
        Returns:
            Topic data including id
        """
        data = {
            "title": title,
            "raw": raw,
            "target_usernames": ",".join(target_usernames),
            "archetype": "private_message"
        }
        
        if created_at:
            data["created_at"] = created_at
        
        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()
        
        result = response.json()
        logger.info("private_message_created", topic_id=result["topic_id"])
        
        return result
    
    def close(self):
        """Close HTTP client."""
        self.client.close()

class DiscourseRateLimitError(Exception):
    """Raised when rate limited by Discourse."""
    
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after} seconds")
```

**Test**:

```python
def test_discourse_create_category(httpx_mock):
    """Test creating a Discourse category."""
    httpx_mock.add_response(
        url="https://discourse.example.com/categories.json",
        method="POST",
        json={
            "category": {
                "id": 123,
                "name": "Test Category",
                "color": "0088CC"
            }
        }
    )
    
    client = DiscourseClient(
        "https://discourse.example.com",
        "test_api_key"
    )
    
    category = client.create_category("Test Category")
    
    assert category["id"] == 123
    assert category["name"] == "Test Category"

def test_discourse_create_topic(httpx_mock):
    """Test creating a Discourse topic."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={
            "id": 456,
            "topic_id": 789,
            "topic_slug": "test-topic"
        }
    )
    
    client = DiscourseClient(
        "https://discourse.example.com",
        "test_api_key"
    )
    
    result = client.create_topic(
        "Test Topic",
        "This is the content",
        category_id=123
    )
    
    assert result["topic_id"] == 789
    assert result["id"] == 456

def test_discourse_rate_limit_handling(httpx_mock):
    """Test handling of rate limit responses."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        status_code=429,
        headers={"Retry-After": "60"}
    )
    
    client = DiscourseClient(
        "https://discourse.example.com",
        "test_api_key"
    )
    
    with pytest.raises(DiscourseRateLimitError) as exc_info:
        client.create_post(123, "test")
    
    assert exc_info.value.retry_after == 60
```

### 3. User Management

#### 3.1 User Mapper

**Test**: Maps Google Chat users to Discourse users

**File**: `src/gchat_mirror/exporters/discourse/user_mapper.py`

```python
# ABOUTME: User mapping and auto-creation for Discourse
# ABOUTME: Creates Discourse users on-demand from Google Chat users

import sqlite3
from typing import Dict, Any, Optional
import re
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient

logger = structlog.get_logger()

class UserMapper:
    """Map Google Chat users to Discourse users."""
    
    def __init__(self, discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
    
    def get_or_create_discourse_user(self, gchat_user_id: str) -> Optional[str]:
        """
        Get Discourse username for Google Chat user, creating if needed.
        
        Args:
            gchat_user_id: Google Chat user ID
        
        Returns:
            Discourse username, or None if user creation fails
        """
        # Check if we have a mapping
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'user' AND source_id = ?
        """, (gchat_user_id,))
        
        result = cursor.fetchone()
        if result:
            return result[0]  # discourse_id is the username
        
        # Get Google Chat user data
        cursor = self.chat_conn.execute("""
            SELECT display_name, email FROM users WHERE id = ?
        """, (gchat_user_id,))
        
        user_data = cursor.fetchone()
        if not user_data:
            logger.error("user_not_found", user_id=gchat_user_id)
            return None
        
        display_name, email = user_data
        
        # Generate Discourse username
        username = self._generate_username(display_name, email)
        
        # Check if user already exists in Discourse
        existing = self.discourse.get_user_by_username(username)
        
        if not existing:
            # Create user
            try:
                result = self.discourse.create_user(
                    email=email or f"{username}@generated.local",
                    username=username,
                    name=display_name
                )
                
                logger.info("discourse_user_created",
                           gchat_user=gchat_user_id,
                           discourse_username=username)
            
            except Exception as e:
                logger.error("user_creation_failed",
                           gchat_user=gchat_user_id,
                           error=str(e))
                return None
        
        # Store mapping
        self.state_conn.execute("""
            INSERT INTO export_mappings 
            (source_type, source_id, discourse_type, discourse_id)
            VALUES ('user', ?, 'user', ?)
        """, (gchat_user_id, username))
        self.state_conn.commit()
        
        return username
    
    def _generate_username(self, display_name: str, email: Optional[str]) -> str:
        """
        Generate Discourse-compatible username from display name.
        
        Rules:
        - Lowercase
        - Alphanumeric + underscore only
        - 3-20 characters
        - No consecutive underscores
        """
        # Start with display name
        username = display_name.lower()
        
        # Replace spaces with underscores
        username = username.replace(' ', '_')
        
        # Remove non-alphanumeric except underscores
        username = re.sub(r'[^a-z0-9_]', '', username)
        
        # Remove consecutive underscores
        username = re.sub(r'_+', '_', username)
        
        # Trim to length
        username = username[:20]
        
        # Ensure minimum length
        if len(username) < 3:
            if email:
                # Try email local part
                username = email.split('@')[0].lower()
                username = re.sub(r'[^a-z0-9_]', '', username)[:20]
        
        # Still too short? Add random suffix
        if len(username) < 3:
            import random
            username = username + '_' + str(random.randint(100, 999))
        
        # Ensure uniqueness by checking database
        base_username = username
        counter = 1
        while self._username_exists(username):
            username = f"{base_username}_{counter}"
            counter += 1
        
        return username
    
    def _username_exists(self, username: str) -> bool:
        """Check if username already mapped."""
        cursor = self.state_conn.execute("""
            SELECT 1 FROM export_mappings
            WHERE source_type = 'user' AND discourse_id = ?
        """, (username,))
        return cursor.fetchone() is not None
```

**Test**:

```python
def test_user_mapper_creates_new_user(tmp_path, httpx_mock):
    """Test creating a new Discourse user."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add Google Chat user
    chat_db.conn.execute("""
        INSERT INTO users (id, display_name, email)
        VALUES ('user1', 'Alice Smith', 'alice@example.com')
    """)
    chat_db.conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/users/alice_smith.json",
        status_code=404
    )
    httpx_mock.add_response(
        url="https://discourse.example.com/users.json",
        method="POST",
        json={"user_id": 123}
    )
    
    client = DiscourseClient("https://discourse.example.com", "key")
    mapper = UserMapper(client, state_db.conn, chat_db.conn)
    
    username = mapper.get_or_create_discourse_user('user1')
    
    assert username == 'alice_smith'
    
    # Verify mapping stored
    cursor = state_db.conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'user' AND source_id = 'user1'
    """)
    assert cursor.fetchone()[0] == 'alice_smith'

def test_user_mapper_handles_existing_user(tmp_path):
    """Test that existing mappings are reused."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Pre-populate mapping
    state_db.conn.execute("""
        INSERT INTO export_mappings 
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('user', 'user1', 'user', 'existing_user')
    """)
    state_db.conn.commit()
    
    client = Mock()
    mapper = UserMapper(client, state_db.conn, chat_db.conn)
    
    username = mapper.get_or_create_discourse_user('user1')
    
    assert username == 'existing_user'
    # Should not call Discourse API
    assert not client.create_user.called

def test_username_generation():
    """Test username generation rules."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    client = Mock()
    mapper = UserMapper(client, state_db.conn, chat_db.conn)
    
    # Normal case
    assert mapper._generate_username("Alice Smith", "alice@example.com") == "alice_smith"
    
    # Special characters
    assert mapper._generate_username("Bob O'Neill", "bob@example.com") == "bob_oneill"
    
    # Non-ASCII
    assert mapper._generate_username("José García", "jose@example.com") == "jos_garca"
    
    # Too short
    username = mapper._generate_username("A", "ab@example.com")
    assert len(username) >= 3
```

### 4. Space to Discourse Mapping

#### 4.1 Space Mapper

**Test**: Maps spaces based on configuration mode

**File**: `src/gchat_mirror/exporters/discourse/space_mapper.py`

```python
# ABOUTME: Space mapping for different Discourse export modes
# ABOUTME: Handles chat/private_messages/hybrid mapping strategies

import sqlite3
from typing import Dict, Any, Optional, Literal
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient

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
```

(Continuing in next response due to length...)

### 5. Thread and Message Export

See implementation details for:
- Thread title generation from first message
- Topic/post creation with proper threading
- Message transformation (markdown conversion)
- Edit history preservation
- Attachment handling with URL caching
- Reaction export

### 6. Failed Export Tracking and Retry

Implement dependency tracking where:
- Failed thread blocks its messages
- Failed message blocks its reactions
- Exponential backoff for retries
- Manual intervention options

### 7. Complete Implementation

Refer to design.md Phase 4 for complete specifications of:
- Message exporter with parallel processing
- Attachment URL caching
- Custom emoji upload
- Read receipt sync (chat mode only)
- State management and idempotency
- CLI commands for starting/stopping exporter

## Completion Criteria

- [ ] Exporter state database created
- [ ] Discourse API client fully functional
- [ ] User auto-creation working
- [ ] All three mapping modes (chat/private_messages/hybrid) work
- [ ] Threads exported as topics/PMs
- [ ] Messages exported with threading
- [ ] Edit history preserved
- [ ] Attachments uploaded with caching
- [ ] Reactions exported
- [ ] Failed exports tracked and retried
- [ ] CLI commands working
- [ ] All tests pass

## Next Steps

After Phase 4, proceed to Phase 5: Polish
