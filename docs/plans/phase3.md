# Phase 3: Real-time Sync - Detailed Specification

## Goal

Robust, adaptive syncing with error handling, backfill capabilities, and monitoring.

## Duration

2-3 weeks

## Prerequisites

- Phase 1 complete (basic sync working)
- Phase 2 complete (all data types stored)

## Tasks

### 1. Adaptive Polling

#### 1.1 Add Space Activity Tracking

**Test**: Can track space activity and adjust poll intervals

**File**: `migrations/011_space_activity.py`

```python
# ABOUTME: Add space activity tracking for adaptive polling
# ABOUTME: Stores message counts and timestamps to determine activity levels

def upgrade(conn):
    """Add activity tracking fields to spaces table."""
    
    # Add activity tracking columns
    conn.execute("""
        ALTER TABLE spaces 
        ADD COLUMN message_count_24h INTEGER DEFAULT 0
    """)
    
    conn.execute("""
        ALTER TABLE spaces 
        ADD COLUMN message_count_7d INTEGER DEFAULT 0
    """)
    
    conn.execute("""
        ALTER TABLE spaces 
        ADD COLUMN poll_interval_seconds INTEGER DEFAULT 300
    """)
    
    conn.execute("""
        ALTER TABLE spaces
        ADD COLUMN last_activity_check TIMESTAMP
    """)
    
    # Create activity log table for trend analysis
    conn.execute("""
        CREATE TABLE IF NOT EXISTS space_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id TEXT NOT NULL,
            
            message_count INTEGER DEFAULT 0,
            
            window_start TIMESTAMP NOT NULL,
            window_end TIMESTAMP NOT NULL,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (space_id) REFERENCES spaces(id) ON DELETE CASCADE
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activity_log_space
        ON space_activity_log(space_id, window_start)
    """)
    
    conn.commit()

def downgrade(conn):
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS space_activity_log")
    # Can't drop columns in SQLite without recreating table
    conn.commit()
```

**Test**:

```python
def test_space_activity_tracking_migration(tmp_path):
    """Test space activity tracking fields."""
    from migrations.011_space_activity import upgrade
    
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    
    # Create spaces table
    conn.execute("""
        CREATE TABLE spaces (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    
    upgrade(conn)
    
    # Insert space with activity
    conn.execute("""
        INSERT INTO spaces 
        (id, name, message_count_24h, poll_interval_seconds)
        VALUES ('space1', 'Test Space', 50, 10)
    """)
    
    cursor = conn.execute("""
        SELECT message_count_24h, poll_interval_seconds 
        FROM spaces WHERE id = 'space1'
    """)
    row = cursor.fetchone()
    assert row[0] == 50
    assert row[1] == 10
    
    conn.close()
```

#### 1.2 Activity Calculator

**Test**: Calculates appropriate poll intervals based on activity

**File**: `src/gchat_mirror/sync/activity_tracker.py`

```python
# ABOUTME: Space activity tracking and adaptive polling
# ABOUTME: Calculates poll intervals based on message frequency

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()

class ActivityTracker:
    """Track space activity and adjust poll intervals."""
    
    # Activity thresholds
    ACTIVE_THRESHOLD = 10  # messages per 24h
    ACTIVE_POLL_INTERVAL = 10  # seconds
    QUIET_POLL_INTERVAL = 300  # 5 minutes
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def update_space_activity(self, space_id: str):
        """
        Update activity metrics for a space.
        
        Calculates message counts for 24h and 7d windows,
        then adjusts poll interval accordingly.
        """
        # Count messages in last 24 hours
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time > datetime('now', '-24 hours')
        """, (space_id,))
        count_24h = cursor.fetchone()[0]
        
        # Count messages in last 7 days
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time > datetime('now', '-7 days')
        """, (space_id,))
        count_7d = cursor.fetchone()[0]
        
        # Determine poll interval
        if count_24h >= self.ACTIVE_THRESHOLD:
            poll_interval = self.ACTIVE_POLL_INTERVAL
            activity_level = 'active'
        else:
            poll_interval = self.QUIET_POLL_INTERVAL
            activity_level = 'quiet'
        
        # Update space record
        self.conn.execute("""
            UPDATE spaces
            SET message_count_24h = ?,
                message_count_7d = ?,
                poll_interval_seconds = ?,
                last_activity_check = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (count_24h, count_7d, poll_interval, space_id))
        
        self.conn.commit()
        
        logger.debug("activity_updated",
                    space_id=space_id,
                    count_24h=count_24h,
                    level=activity_level,
                    poll_interval=poll_interval)
        
        return poll_interval
    
    def get_spaces_to_poll(self) -> list:
        """
        Get spaces that need polling based on their intervals.
        
        Returns list of space IDs that should be polled now.
        """
        cursor = self.conn.execute("""
            SELECT id, poll_interval_seconds, last_synced_at
            FROM spaces
            WHERE sync_status = 'active'
              AND (
                  last_synced_at IS NULL
                  OR datetime(last_synced_at, 
                      '+' || poll_interval_seconds || ' seconds') 
                      <= datetime('now')
              )
            ORDER BY last_synced_at ASC NULLS FIRST
        """)
        
        return [row[0] for row in cursor.fetchall()]
    
    def log_activity_window(self, space_id: str, 
                           window_start: datetime,
                           window_end: datetime):
        """Log activity for a time window (for trend analysis)."""
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time >= ?
              AND create_time < ?
        """, (space_id, window_start, window_end))
        
        message_count = cursor.fetchone()[0]
        
        self.conn.execute("""
            INSERT INTO space_activity_log
            (space_id, message_count, window_start, window_end)
            VALUES (?, ?, ?, ?)
        """, (space_id, message_count, window_start, window_end))
        
        self.conn.commit()
```

**Test**:

```python
def test_activity_tracker_active_space(tmp_path):
    """Test that active spaces get short poll intervals."""
    db = setup_test_database(tmp_path)
    tracker = ActivityTracker(db.conn)
    
    # Create space with recent messages
    db.conn.execute("""
        INSERT INTO spaces (id, name) VALUES ('space1', 'Active Space')
    """)
    
    now = datetime.now()
    for i in range(15):
        db.conn.execute("""
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, 'space1', 'msg', ?)
        """, (f'msg{i}', (now - timedelta(hours=i)).isoformat()))
    
    db.conn.commit()
    
    # Update activity
    poll_interval = tracker.update_space_activity('space1')
    
    assert poll_interval == 10  # Active threshold
    
    # Verify database updated
    cursor = db.conn.execute("""
        SELECT message_count_24h, poll_interval_seconds 
        FROM spaces WHERE id = 'space1'
    """)
    row = cursor.fetchone()
    assert row['message_count_24h'] >= 10
    assert row['poll_interval_seconds'] == 10

def test_activity_tracker_quiet_space(tmp_path):
    """Test that quiet spaces get long poll intervals."""
    db = setup_test_database(tmp_path)
    tracker = ActivityTracker(db.conn)
    
    # Create space with no recent messages
    db.conn.execute("""
        INSERT INTO spaces (id, name) VALUES ('space1', 'Quiet Space')
    """)
    db.conn.commit()
    
    # Update activity
    poll_interval = tracker.update_space_activity('space1')
    
    assert poll_interval == 300  # Quiet threshold
    
    cursor = db.conn.execute("""
        SELECT message_count_24h, poll_interval_seconds 
        FROM spaces WHERE id = 'space1'
    """)
    row = cursor.fetchone()
    assert row['message_count_24h'] == 0
    assert row['poll_interval_seconds'] == 300

def test_get_spaces_to_poll(tmp_path):
    """Test selecting spaces that need polling."""
    db = setup_test_database(tmp_path)
    tracker = ActivityTracker(db.conn)
    
    # Create spaces with different poll times
    past = (datetime.now() - timedelta(minutes=10)).isoformat()
    recent = (datetime.now() - timedelta(seconds=5)).isoformat()
    
    db.conn.execute("""
        INSERT INTO spaces 
        (id, name, sync_status, poll_interval_seconds, last_synced_at)
        VALUES 
        ('space1', 'Old', 'active', 60, ?),
        ('space2', 'Recent', 'active', 60, ?),
        ('space3', 'Never', 'active', 60, NULL)
    """, (past, recent))
    db.conn.commit()
    
    # Get spaces to poll
    to_poll = tracker.get_spaces_to_poll()
    
    # Should include space1 (old) and space3 (never), not space2 (recent)
    assert 'space1' in to_poll
    assert 'space3' in to_poll
    # space2 might be in if current time allows
```

#### 1.3 Update Sync Daemon for Adaptive Polling

**Test**: Sync daemon uses adaptive intervals

**File**: Update `src/gchat_mirror/sync/daemon.py`

```python
# Add to SyncDaemon class:

from gchat_mirror.sync.activity_tracker import ActivityTracker

def __init__(self, data_dir: Path, config: dict):
    # ... existing init ...
    self.activity_tracker = None

def start(self):
    # ... existing start logic ...
    
    self.activity_tracker = ActivityTracker(self.chat_db.conn)
    
    # Run initial sync
    self.initial_sync()
    
    # Start continuous polling
    self.running = True
    self.poll_loop()

def poll_loop(self):
    """Continuous polling loop with adaptive intervals."""
    logger.info("poll_loop_started")
    
    while self.running:
        try:
            # Get spaces that need polling
            spaces_to_poll = self.activity_tracker.get_spaces_to_poll()
            
            if spaces_to_poll:
                logger.info("polling_spaces", count=len(spaces_to_poll))
                
                for space_id in spaces_to_poll:
                    if not self.running:
                        break
                    
                    # Fetch space data
                    cursor = self.chat_db.conn.execute("""
                        SELECT * FROM spaces WHERE id = ?
                    """, (space_id,))
                    space = dict(cursor.fetchone())
                    
                    # Sync the space
                    self.sync_space(space)
                    
                    # Update activity metrics
                    self.activity_tracker.update_space_activity(space_id)
            
            # Sleep briefly before checking again
            time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("interrupt_received")
            break
        except Exception as e:
            logger.error("poll_loop_error", error=str(e), exc_info=True)
            time.sleep(5)  # Back off on error
```

**Test**:

```python
def test_adaptive_polling_daemon(tmp_path, httpx_mock):
    """Test that daemon uses adaptive polling intervals."""
    # Setup with active and quiet spaces
    # Mock API responses
    # Run daemon briefly
    # Verify active space polled more frequently
    pass  # Implementation similar to existing daemon tests
```

### 2. Space Discovery and Access Management

#### 2.1 Add Access Denied Tracking

**Test**: Can mark spaces as access_denied

**File**: Update `migrations/011_space_activity.py` to add:

```python
# Add to upgrade():

conn.execute("""
    ALTER TABLE spaces
    ADD COLUMN access_denied_at TIMESTAMP
""")

conn.execute("""
    ALTER TABLE spaces
    ADD COLUMN access_denied_reason TEXT
""")
```

#### 2.2 Handle Access Denied

**Test**: Handles 403 errors gracefully

**File**: Update `src/gchat_mirror/sync/daemon.py`

```python
# Add error handling to sync_space:

def sync_space(self, space: dict):
    """Sync a single space with error handling."""
    space_id = space["name"] if isinstance(space, dict) and "name" in space else space
    
    try:
        logger.info("syncing_space", space_id=space_id)
        
        # Store/update space metadata
        if isinstance(space, dict):
            self.storage.upsert_space(space)
        
        # Fetch messages
        page_token = self.storage.get_space_sync_cursor(space_id)
        messages_synced = 0
        
        while True:
            try:
                response = self.client.list_messages(
                    space_id,
                    page_token=page_token
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    # Access denied - mark space
                    self._mark_space_access_denied(
                        space_id,
                        "Access denied by Google Chat API"
                    )
                    logger.warning("space_access_denied", space_id=space_id)
                    return
                elif e.response.status_code == 404:
                    # Space not found - might be deleted
                    self._mark_space_access_denied(
                        space_id,
                        "Space not found (possibly deleted)"
                    )
                    logger.warning("space_not_found", space_id=space_id)
                    return
                else:
                    # Other HTTP error - re-raise for retry logic
                    raise
            
            messages = response.get("messages", [])
            for message in messages:
                self._process_message(message)
                messages_synced += 1
            
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        
        # Update sync cursor and timestamp
        self.storage.update_space_sync_cursor(space_id, None)
        self.chat_db.conn.execute("""
            UPDATE spaces
            SET last_synced_at = CURRENT_TIMESTAMP,
                last_message_time = (
                    SELECT MAX(create_time) FROM messages 
                    WHERE space_id = ?
                )
            WHERE id = ?
        """, (space_id, space_id))
        self.chat_db.conn.commit()
        
        logger.info("space_synced",
                   space_id=space_id,
                   messages=messages_synced)
    
    except Exception as e:
        logger.error("space_sync_error",
                    space_id=space_id,
                    error=str(e),
                    exc_info=True)
        # Don't mark as access_denied for other errors
        raise

def _mark_space_access_denied(self, space_id: str, reason: str):
    """Mark a space as access denied."""
    self.chat_db.conn.execute("""
        UPDATE spaces
        SET sync_status = 'access_denied',
            access_denied_at = CURRENT_TIMESTAMP,
            access_denied_reason = ?
        WHERE id = ?
    """, (reason, space_id))
    self.chat_db.conn.commit()

def discover_spaces(self):
    """Discover all accessible spaces from Google Chat."""
    try:
        spaces = self.client.list_spaces()
        logger.info("spaces_discovered", count=len(spaces))
        
        # Update database with discovered spaces
        for space in spaces:
            self.storage.upsert_space(space)
        
        return spaces
    
    except Exception as e:
        logger.error("space_discovery_error", error=str(e), exc_info=True)
        raise
```

**Test**:

```python
def test_handle_access_denied(tmp_path, httpx_mock):
    """Test that 403 errors mark spaces as access_denied."""
    chat_db = setup_test_chat_db(tmp_path)
    
    # Setup daemon
    daemon = SyncDaemon(tmp_path, {})
    daemon.chat_db = chat_db
    daemon.storage = SyncStorage(chat_db.conn)
    
    # Create space
    chat_db.conn.execute("""
        INSERT INTO spaces (id, name, sync_status)
        VALUES ('space1', 'Test Space', 'active')
    """)
    chat_db.conn.commit()
    
    # Mock 403 response
    httpx_mock.add_response(
        url="https://chat.googleapis.com/v1/space1/messages",
        status_code=403
    )
    
    # Mock credentials
    mock_creds = Mock(token="test")
    daemon.client = GoogleChatClient(mock_creds)
    
    # Try to sync
    daemon.sync_space({'name': 'space1'})
    
    # Verify marked as access_denied
    cursor = chat_db.conn.execute("""
        SELECT sync_status, access_denied_reason 
        FROM spaces WHERE id = 'space1'
    """)
    row = cursor.fetchone()
    assert row['sync_status'] == 'access_denied'
    assert 'Access denied' in row['access_denied_reason']
```

### 3. Backfill Command

#### 3.1 Backfill Implementation

**Test**: Can backfill historical messages

**File**: Update `src/gchat_mirror/cli/sync.py`

```python
# Update backfill command:

@sync.command()
@click.option('--space-id', help='Space ID to backfill (omit for all)')
@click.option('--days', type=int, default=365, help='Days of history to fetch')
@click.option('--batch-size', type=int, default=100, help='Messages per API call')
@click.pass_context
def backfill(ctx, space_id: str, days: int, batch_size: int):
    """Backfill historical messages."""
    from datetime import datetime, timedelta
    from gchat_mirror.sync.backfill import BackfillManager
    
    data_dir = ctx.obj['data_dir']
    config_dir = ctx.obj['config_dir']
    
    # Load config
    config_file = config_dir / 'sync' / 'config.toml'
    if config_file.exists():
        config = toml.load(config_file)
    else:
        config = {}
    
    # Create backfill manager
    manager = BackfillManager(data_dir, config)
    
    click.echo(f"Backfilling {days} days of history...")
    
    if space_id:
        # Backfill single space
        click.echo(f"Space: {space_id}")
        manager.backfill_space(space_id, days, batch_size)
    else:
        # Backfill all spaces
        manager.backfill_all_spaces(days, batch_size)
    
    click.echo("Backfill complete!")
```

**File**: `src/gchat_mirror/sync/backfill.py`

```python
# ABOUTME: Backfill manager for historical message retrieval
# ABOUTME: Handles fetching older messages beyond initial sync window

from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import structlog
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from gchat_mirror.common.database import Database
from gchat_mirror.sync.auth import authenticate
from gchat_mirror.sync.google_client import GoogleChatClient
from gchat_mirror.sync.storage import SyncStorage

logger = structlog.get_logger()

class BackfillManager:
    """Manage backfilling historical messages."""
    
    def __init__(self, data_dir: Path, config: dict):
        self.data_dir = Path(data_dir)
        self.config = config
        self.chat_db = Database(self.data_dir / "sync" / "chat.db")
    
    def backfill_all_spaces(self, days: int, batch_size: int = 100):
        """Backfill all active spaces."""
        self.chat_db.connect()
        
        # Get all active spaces
        cursor = self.chat_db.conn.execute("""
            SELECT id, display_name 
            FROM spaces 
            WHERE sync_status = 'active'
            ORDER BY display_name
        """)
        spaces = cursor.fetchall()
        
        logger.info("backfill_starting", space_count=len(spaces), days=days)
        
        # Authenticate
        creds = authenticate(self.config.get("credential_key", "gchat-sync"))
        client = GoogleChatClient(creds)
        storage = SyncStorage(self.chat_db.conn)
        
        # Progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}")
        ) as progress:
            
            task = progress.add_task("Backfilling spaces...", total=len(spaces))
            
            for space_id, display_name in spaces:
                progress.update(task, description=f"Backfilling {display_name}")
                
                self._backfill_space_impl(
                    client,
                    storage,
                    space_id,
                    days,
                    batch_size
                )
                
                progress.advance(task)
        
        client.close()
        self.chat_db.close()
        
        logger.info("backfill_complete")
    
    def backfill_space(self, space_id: str, days: int, batch_size: int = 100):
        """Backfill a single space."""
        self.chat_db.connect()
        
        # Authenticate
        creds = authenticate(self.config.get("credential_key", "gchat-sync"))
        client = GoogleChatClient(creds)
        storage = SyncStorage(self.chat_db.conn)
        
        logger.info("backfill_space_starting", space_id=space_id, days=days)
        
        messages_fetched = self._backfill_space_impl(
            client,
            storage,
            space_id,
            days,
            batch_size
        )
        
        client.close()
        self.chat_db.close()
        
        logger.info("backfill_space_complete",
                   space_id=space_id,
                   messages=messages_fetched)
    
    def _backfill_space_impl(self, client: GoogleChatClient,
                            storage: SyncStorage,
                            space_id: str,
                            days: int,
                            batch_size: int) -> int:
        """Internal backfill implementation."""
        # Calculate time window
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        # Get oldest message we have
        cursor = self.chat_db.conn.execute("""
            SELECT MIN(create_time) FROM messages WHERE space_id = ?
        """, (space_id,))
        oldest = cursor.fetchone()[0]
        
        if oldest:
            # Only backfill before oldest message
            oldest_dt = datetime.fromisoformat(oldest.replace('Z', '+00:00'))
            if oldest_dt <= start_time:
                logger.info("backfill_not_needed",
                           space_id=space_id,
                           oldest=oldest)
                return 0
            
            end_time = oldest_dt
        
        messages_fetched = 0
        page_token = None
        
        # Fetch messages in the time window
        while True:
            try:
                response = client.list_messages(
                    space_id,
                    page_token=page_token,
                    page_size=batch_size,
                    filter=f'createTime < "{end_time.isoformat()}"'
                )
            except Exception as e:
                logger.error("backfill_error",
                           space_id=space_id,
                           error=str(e))
                break
            
            messages = response.get("messages", [])
            if not messages:
                break
            
            for message in messages:
                # Check if we're past our start time
                msg_time = datetime.fromisoformat(
                    message['createTime'].replace('Z', '+00:00')
                )
                if msg_time < start_time:
                    # Reached the limit
                    return messages_fetched
                
                # Process message (includes sender)
                sender = message.get("sender")
                if sender:
                    storage.upsert_user(sender)
                
                # Insert message (use insert not update for backfill)
                try:
                    storage.insert_message(message)
                    messages_fetched += 1
                except Exception:
                    # Message might already exist, skip
                    pass
            
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        
        return messages_fetched
```

**Test**:

```python
def test_backfill_single_space(tmp_path, httpx_mock):
    """Test backfilling a single space."""
    # Setup database
    db_path = tmp_path / "sync" / "chat.db"
    # ... setup code ...
    
    # Mock API responses with old messages
    httpx_mock.add_response(
        url__regex=r".*space1/messages.*",
        json={
            "messages": [
                {
                    "name": "spaces/space1/messages/old1",
                    "text": "old message",
                    "createTime": "2024-01-01T10:00:00Z",
                    "sender": {"name": "user1", "displayName": "Alice"}
                }
            ]
        }
    )
    
    manager = BackfillManager(tmp_path, {'credential_key': 'test'})
    
    with patch('gchat_mirror.sync.auth.authenticate'):
        manager.backfill_space('space1', days=365)
    
    # Verify old message was stored
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT text FROM messages WHERE id = 'spaces/space1/messages/old1'
    """)
    assert cursor.fetchone()[0] == 'old message'
```

### 4. Error Handling with Exponential Backoff

#### 4.1 Retry Logic Manager

**Test**: Implements exponential backoff

**File**: `src/gchat_mirror/common/retry.py`

```python
# ABOUTME: Retry logic with exponential backoff for API calls
# ABOUTME: Handles transient failures with progressive delays

import time
from typing import Callable, TypeVar, Optional
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()

T = TypeVar('T')

class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(self,
                 max_attempts: int = 5,
                 initial_delay: float = 1.0,
                 max_delay: float = 300.0,
                 backoff_factor: float = 2.0):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-indexed)."""
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)

def with_retry(config: RetryConfig,
               func: Callable[[], T],
               should_retry: Optional[Callable[[Exception], bool]] = None) -> T:
    """
    Execute function with retry logic.
    
    Args:
        config: Retry configuration
        func: Function to execute
        should_retry: Optional predicate to determine if exception is retryable
    
    Returns:
        Result of func()
    
    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            return func()
        
        except Exception as e:
            last_exception = e
            
            # Check if we should retry this exception
            if should_retry and not should_retry(e):
                logger.info("exception_not_retryable", error=str(e))
                raise
            
            # Check if we have more attempts
            if attempt + 1 >= config.max_attempts:
                logger.error("max_retries_exceeded",
                           attempts=config.max_attempts,
                           error=str(e))
                raise
            
            # Calculate delay
            delay = config.get_delay(attempt)
            
            logger.warning("retry_after_error",
                         attempt=attempt + 1,
                         max_attempts=config.max_attempts,
                         delay_seconds=delay,
                         error=str(e))
            
            time.sleep(delay)
    
    # Should never reach here, but satisfy type checker
    raise last_exception

def is_retryable_http_error(exception: Exception) -> bool:
    """Determine if an HTTP error is retryable."""
    import httpx
    
    if not isinstance(exception, httpx.HTTPStatusError):
        # Network errors, timeouts are retryable
        return isinstance(exception, (httpx.TimeoutException,
                                     httpx.NetworkError,
                                     httpx.ConnectError))
    
    # 403 and 404 are not retryable (access denied / not found)
    if exception.response.status_code in (403, 404):
        return False
    
    # 429 (rate limit) is retryable
    if exception.response.status_code == 429:
        return True
    
    # 5xx errors are retryable
    if exception.response.status_code >= 500:
        return True
    
    # 4xx client errors (except 429) are not retryable
    if exception.response.status_code >= 400:
        return False
    
    return True
```

**Test**:

```python
def test_retry_success_after_failures():
    """Test that retry succeeds after transient failures."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)
    
    call_count = 0
    
    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Transient error")
        return "success"
    
    result = with_retry(config, flaky_function)
    
    assert result == "success"
    assert call_count == 3

def test_retry_exhausted():
    """Test that retry gives up after max attempts."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)
    
    def always_fails():
        raise Exception("Permanent error")
    
    with pytest.raises(Exception, match="Permanent error"):
        with_retry(config, always_fails)

def test_retry_with_non_retryable():
    """Test that non-retryable errors fail immediately."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)
    
    call_count = 0
    
    def failing_function():
        nonlocal call_count
        call_count += 1
        raise ValueError("Bad input")
    
    def should_retry(e):
        return not isinstance(e, ValueError)
    
    with pytest.raises(ValueError):
        with_retry(config, failing_function, should_retry=should_retry)
    
    assert call_count == 1  # Should not retry

def test_exponential_backoff_calculation():
    """Test backoff delay calculation."""
    config = RetryConfig(
        initial_delay=1.0,
        backoff_factor=2.0,
        max_delay=10.0
    )
    
    assert config.get_delay(0) == 1.0  # 1 * 2^0
    assert config.get_delay(1) == 2.0  # 1 * 2^1
    assert config.get_delay(2) == 4.0  # 1 * 2^2
    assert config.get_delay(3) == 8.0  # 1 * 2^3
    assert config.get_delay(4) == 10.0  # capped at max_delay
    assert config.get_delay(5) == 10.0  # capped at max_delay
```

### 5. Health Check HTTP Endpoint

#### 5.1 Health Check Server

**Test**: HTTP endpoint responds with status

**File**: `src/gchat_mirror/sync/health_server.py`

```python
# ABOUTME: HTTP health check endpoint for monitoring
# ABOUTME: Provides status information on port 4981

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from datetime import datetime
import structlog

logger = structlog.get_logger()

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Handle health check HTTP requests."""
    
    def do_GET(self):
        """Handle GET request."""
        if self.path == '/health':
            self.send_health_response()
        elif self.path == '/metrics':
            self.send_metrics_response()
        else:
            self.send_not_found()
    
    def send_health_response(self):
        """Send health check response."""
        # Get status from daemon
        daemon = self.server.daemon
        
        status = {
            'status': 'ok' if daemon.running else 'stopped',
            'timestamp': datetime.now().isoformat(),
            'spaces_synced': daemon.get_space_count(),
            'messages_synced': daemon.get_message_count(),
            'last_sync': daemon.get_last_sync_time(),
        }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())
    
    def send_metrics_response(self):
        """Send metrics in Prometheus format."""
        daemon = self.server.daemon
        
        metrics = f"""# HELP gchat_mirror_spaces_total Total number of spaces
# TYPE gchat_mirror_spaces_total gauge
gchat_mirror_spaces_total {daemon.get_space_count()}

# HELP gchat_mirror_messages_total Total number of messages
# TYPE gchat_mirror_messages_total gauge
gchat_mirror_messages_total {daemon.get_message_count()}

# HELP gchat_mirror_up Whether the sync daemon is running
# TYPE gchat_mirror_up gauge
gchat_mirror_up {1 if daemon.running else 0}
"""
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(metrics.encode())
    
    def send_not_found(self):
        """Send 404 response."""
        self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        """Override to use structlog."""
        logger.info("health_check_request",
                   method=self.command,
                   path=self.path,
                   client=self.client_address[0])

class HealthCheckServer:
    """HTTP server for health checks."""
    
    def __init__(self, daemon, port: int = 4981):
        self.daemon = daemon
        self.port = port
        self.server = None
        self.thread = None
    
    def start(self):
        """Start the health check server."""
        self.server = HTTPServer(('0.0.0.0', self.port), HealthCheckHandler)
        self.server.daemon = self.daemon
        
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        
        logger.info("health_check_server_started", port=self.port)
    
    def stop(self):
        """Stop the health check server."""
        if self.server:
            self.server.shutdown()
            logger.info("health_check_server_stopped")
```

**File**: Update `src/gchat_mirror/sync/daemon.py`

```python
# Add to SyncDaemon class:

from gchat_mirror.sync.health_server import HealthCheckServer

def __init__(self, data_dir: Path, config: dict):
    # ... existing init ...
    self.health_server = None

def start(self):
    # ... existing start logic ...
    
    # Start health check server
    port = self.config.get('monitoring', {}).get('health_check_port', 4981)
    self.health_server = HealthCheckServer(self, port)
    self.health_server.start()
    
    # ... rest of start logic ...

def stop(self):
    # ... existing stop logic ...
    
    if self.health_server:
        self.health_server.stop()

def get_space_count(self) -> int:
    """Get total space count."""
    cursor = self.chat_db.conn.execute("SELECT COUNT(*) FROM spaces")
    return cursor.fetchone()[0]

def get_message_count(self) -> int:
    """Get total message count."""
    cursor = self.chat_db.conn.execute("SELECT COUNT(*) FROM messages")
    return cursor.fetchone()[0]

def get_last_sync_time(self) -> str:
    """Get timestamp of last sync."""
    cursor = self.chat_db.conn.execute("""
        SELECT MAX(last_synced_at) FROM spaces
    """)
    result = cursor.fetchone()[0]
    return result if result else 'never'
```

**Test**:

```python
def test_health_check_endpoint(tmp_path):
    """Test health check HTTP endpoint."""
    import httpx
    
    # Create minimal daemon
    daemon = Mock()
    daemon.running = True
    daemon.get_space_count = Mock(return_value=5)
    daemon.get_message_count = Mock(return_value=100)
    daemon.get_last_sync_time = Mock(return_value='2025-01-15T10:00:00Z')
    
    # Start server
    server = HealthCheckServer(daemon, port=0)  # Random port
    server.start()
    
    # Get actual port
    port = server.server.server_address[1]
    
    # Query health endpoint
    response = httpx.get(f'http://localhost:{port}/health')
    
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert data['spaces_synced'] == 5
    assert data['messages_synced'] == 100
    
    # Stop server
    server.stop()
```

### 6. Progress Bars with Rich

#### 6.1 Add Progress Display

**Test**: Shows progress during sync

**File**: Update `src/gchat_mirror/sync/daemon.py`

```python
# Add progress display to initial_sync:

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

def initial_sync(self):
    """Run initial sync for all spaces with progress display."""
    logger.info("initial_sync_starting")
    
    # Discover spaces
    spaces = self.discover_spaces()
    
    if not spaces:
        logger.warning("no_spaces_found")
        return
    
    logger.info("spaces_discovered", count=len(spaces))
    
    # Sync each space with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn()
    ) as progress:
        
        task = progress.add_task("Syncing spaces...", total=len(spaces))
        
        for space in spaces:
            space_name = space.get('displayName', space.get('name', 'Unknown'))
            progress.update(task, description=f"Syncing {space_name}")
            
            try:
                self.sync_space(space)
            except Exception as e:
                logger.error("space_sync_failed",
                           space=space.get('name'),
                           error=str(e))
                # Continue with other spaces
            
            progress.advance(task)
    
    logger.info("initial_sync_complete")
```

**Test**:

```python
def test_sync_with_progress(tmp_path, capsys):
    """Test that sync shows progress bars."""
    # ... setup code ...
    
    daemon = SyncDaemon(tmp_path, {})
    # ... mock setup ...
    
    daemon.initial_sync()
    
    # Capture output would show progress bars
    # (hard to test programmatically, mainly for visual confirmation)
```

### 7. Database Integrity Checks

#### 7.1 Comprehensive Integrity Checker

**Test**: Detects various integrity issues

**File**: `src/gchat_mirror/common/integrity.py`

```python
# ABOUTME: Database integrity checking and repair
# ABOUTME: Validates foreign keys, orphaned records, and data consistency

import sqlite3
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()

class IntegrityChecker:
    """Check database integrity."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.issues = []
    
    def check_all(self) -> bool:
        """
        Run all integrity checks.
        
        Returns:
            True if all checks pass, False if issues found
        """
        self.issues = []
        
        # SQLite's built-in integrity check
        self._check_sqlite_integrity()
        
        # Foreign key violations
        self._check_foreign_keys()
        
        # Orphaned records
        self._check_orphans()
        
        # Data consistency
        self._check_data_consistency()
        
        if self.issues:
            for issue in self.issues:
                logger.warning("integrity_issue", **issue)
            return False
        
        logger.info("integrity_check_passed")
        return True
    
    def _check_sqlite_integrity(self):
        """Run SQLite's PRAGMA integrity_check."""
        cursor = self.conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        
        if result != "ok":
            self.issues.append({
                'type': 'sqlite_integrity',
                'message': result
            })
    
    def _check_foreign_keys(self):
        """Check for foreign key violations."""
        cursor = self.conn.execute("PRAGMA foreign_key_check")
        violations = cursor.fetchall()
        
        for violation in violations:
            self.issues.append({
                'type': 'foreign_key_violation',
                'table': violation[0],
                'rowid': violation[1],
                'parent': violation[2],
                'fkid': violation[3]
            })
    
    def _check_orphans(self):
        """Check for orphaned records."""
        # Messages without spaces
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages m
            WHERE NOT EXISTS (
                SELECT 1 FROM spaces s WHERE s.id = m.space_id
            )
        """)
        orphan_messages = cursor.fetchone()[0]
        if orphan_messages > 0:
            self.issues.append({
                'type': 'orphaned_messages',
                'count': orphan_messages
            })
        
        # Reactions without messages
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM reactions r
            WHERE NOT EXISTS (
                SELECT 1 FROM messages m WHERE m.id = r.message_id
            )
        """)
        orphan_reactions = cursor.fetchone()[0]
        if orphan_reactions > 0:
            self.issues.append({
                'type': 'orphaned_reactions',
                'count': orphan_reactions
            })
        
        # Attachments without messages
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM attachments a
            WHERE NOT EXISTS (
                SELECT 1 FROM messages m WHERE m.id = a.message_id
            )
        """)
        orphan_attachments = cursor.fetchone()[0]
        if orphan_attachments > 0:
            self.issues.append({
                'type': 'orphaned_attachments',
                'count': orphan_attachments
            })
    
    def _check_data_consistency(self):
        """Check data consistency rules."""
        # Spaces with invalid sync_status
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM spaces
            WHERE sync_status NOT IN ('active', 'access_denied', 'paused')
        """)
        invalid_status = cursor.fetchone()[0]
        if invalid_status > 0:
            self.issues.append({
                'type': 'invalid_sync_status',
                'count': invalid_status
            })
        
        # Messages with future timestamps
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM messages
            WHERE create_time > datetime('now')
        """)
        future_messages = cursor.fetchone()[0]
        if future_messages > 0:
            self.issues.append({
                'type': 'future_timestamps',
                'count': future_messages
            })
```

**Test**:

```python
def test_integrity_checker_passes_clean_db(tmp_path):
    """Test integrity check on clean database."""
    db = setup_test_database(tmp_path)
    
    # Add valid data
    db.conn.execute("""
        INSERT INTO spaces (id, name, sync_status)
        VALUES ('space1', 'Test', 'active')
    """)
    db.conn.execute("""
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg1', 'space1', 'test')
    """)
    db.conn.commit()
    
    checker = IntegrityChecker(db.conn)
    assert checker.check_all() == True
    assert len(checker.issues) == 0

def test_integrity_checker_detects_orphans(tmp_path):
    """Test detection of orphaned records."""
    db = setup_test_database(tmp_path)
    
    # Create orphaned message (no parent space)
    db.conn.execute("""
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg1', 'nonexistent_space', 'orphan')
    """)
    db.conn.commit()
    
    checker = IntegrityChecker(db.conn)
    assert checker.check_all() == False
    assert any(i['type'] == 'orphaned_messages' for i in checker.issues)
```

### 8. Update CLI with New Commands

#### 8.1 Add Integrity Check Command

**Test**: CLI can run integrity checks

**File**: Update `src/gchat_mirror/cli/main.py`

```python
# Add integrity-check command:

@cli.command()
@click.pass_context
def integrity_check(ctx):
    """Run database integrity checks."""
    from gchat_mirror.common.integrity import IntegrityChecker
    import sqlite3
    
    data_dir = ctx.obj['data_dir']
    db_path = data_dir / 'sync' / 'chat.db'
    
    if not db_path.exists():
        click.echo("No database found.")
        return
    
    conn = sqlite3.connect(db_path)
    checker = IntegrityChecker(conn)
    
    click.echo("Running integrity checks...")
    
    if checker.check_all():
        click.echo("✓ All integrity checks passed")
    else:
        click.echo("✗ Integrity issues found:")
        for issue in checker.issues:
            click.echo(f"  - {issue['type']}: {issue}")
    
    conn.close()
```

#### 8.2 Add Health Command

**Test**: CLI can query health endpoint

**File**: Update `src/gchat_mirror/cli/main.py`

```python
# Add health command:

@cli.command()
@click.option('--port', default=4981, help='Health check port')
@click.pass_context
def health(ctx, port: int):
    """Query health check endpoint."""
    import httpx
    
    try:
        response = httpx.get(f'http://localhost:{port}/health', timeout=5.0)
        
        if response.status_code == 200:
            data = response.json()
            click.echo(f"Status: {data['status']}")
            click.echo(f"Spaces: {data['spaces_synced']}")
            click.echo(f"Messages: {data['messages_synced']}")
            click.echo(f"Last sync: {data['last_sync']}")
        else:
            click.echo(f"Health check failed: HTTP {response.status_code}")
    
    except httpx.ConnectError:
        click.echo("Could not connect to health check endpoint.")
        click.echo("Is the sync daemon running?")
    except Exception as e:
        click.echo(f"Error: {e}")
```

## Completion Criteria

- [ ] Adaptive polling implemented with activity tracking
- [ ] Active spaces polled every 10 seconds
- [ ] Quiet spaces polled every 5 minutes
- [ ] Space discovery handles access_denied (403/404) gracefully
- [ ] Backfill command works for single space and all spaces
- [ ] Exponential backoff retry logic implemented
- [ ] Retryable vs non-retryable errors distinguished
- [ ] Health check HTTP endpoint responds on port 4981
- [ ] Progress bars show during initial sync and backfill
- [ ] Database integrity checks detect common issues
- [ ] CLI commands for integrity-check and health work
- [ ] All unit tests pass
- [ ] Integration tests verify adaptive polling behavior
- [ ] Error handling tested with various failure scenarios

## Next Steps

After Phase 3 completion, proceed to Phase 4: Discourse Exporter, which will implement the export client for pushing data to Discourse.
