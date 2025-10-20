# Phase 4.3: User Management

## Goal

Implement user mapping and auto-creation from Google Chat users to Discourse users.

## Duration

1 day

## Prerequisites

- Phase 4.1 complete (database schema)
- Phase 4.2 complete (Discourse API client)

## Overview

The user mapper automatically creates Discourse users from Google Chat users on-demand, with:

1. **Username Generation** - Transform display names into valid Discourse usernames
2. **Auto-Creation** - Create users automatically when first mentioned/posting
3. **Mapping Cache** - Cache Google Chat ID → Discourse username mappings
4. **Uniqueness Handling** - Handle duplicate usernames with counters

## Tasks

### 1. User Mapper Implementation

#### 1.1 User Mapping and Creation

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

def test_username_uniqueness():
    """Test that duplicate usernames get unique suffixes."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    # Add existing mapping
    state_db.conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('user', 'user1', 'user', 'alice_smith')
    """)
    state_db.conn.commit()
    
    client = Mock()
    mapper = UserMapper(client, state_db.conn, chat_db.conn)
    
    # Should generate alice_smith_1 since alice_smith exists
    username = mapper._generate_username("Alice Smith", "alice@example.com")
    assert username == "alice_smith_1"
```

## Username Generation Rules

### Valid Characters
- Lowercase letters (a-z)
- Numbers (0-9)
- Underscores (_)

### Transformations
1. Convert to lowercase
2. Replace spaces with underscores
3. Remove all other characters
4. Remove consecutive underscores
5. Ensure 3-20 character length
6. Add counter suffix if duplicate

### Examples
- "Alice Smith" → "alice_smith"
- "Bob O'Neill" → "bob_oneill"
- "user@example.com" → "user"
- "José García" → "jos_garca"
- "AB" → "ab_123" (too short, random suffix)
- "Alice Smith" (duplicate) → "alice_smith_1"

## Completion Criteria

- [ ] User mapper creates Discourse users on-demand
- [ ] Username generation follows all rules
- [ ] Duplicate usernames handled with counters
- [ ] Mappings cached in database
- [ ] Existing mappings reused
- [ ] Email fallback for short names
- [ ] All tests pass

## Next Steps

After Phase 4.3, proceed to Phase 4.4: Space to Discourse Mapping
