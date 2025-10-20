# Phase 4.6: Failed Export Tracking and Retry

## Goal

Implement robust error handling for Discourse exports with dependency tracking, exponential backoff, and manual intervention capabilities.

## Duration

3-4 days

## Prerequisites

- Phase 4.1-4.5 complete (database, API client, mapping, thread/message export)
- Failed exports table in state database

## Overview

This phase ensures reliable export operation by:

1. **Dependency Tracking** - Failed exports block dependent operations (thread → messages → reactions)
2. **Exponential Backoff** - Retry failed exports with increasing delays
3. **Error Classification** - Distinguish permanent vs temporary failures
4. **Manual Intervention** - Tools to inspect and resolve blocked exports
5. **Progress Monitoring** - Track export state per space

## Tasks

### 1. Retry Configuration

#### 1.1 Retry Configuration Manager

**Test**: Configures retry behavior with exponential backoff

**File**: `src/gchat_mirror/exporters/discourse/retry_config.py`

```python
# ABOUTME: Retry configuration for failed Discourse exports
# ABOUTME: Implements exponential backoff and retry limits

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import structlog

logger = structlog.get_logger()

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    
    # Initial retry delay (seconds)
    initial_delay: int = 60
    
    # Maximum retry delay (seconds)
    max_delay: int = 3600  # 1 hour
    
    # Backoff multiplier
    backoff_multiplier: float = 2.0
    
    # Maximum retry attempts
    max_attempts: int = 10
    
    # Jitter percentage (0.0-1.0)
    jitter: float = 0.1

    def calculate_next_retry(self, error_count: int) -> datetime:
        """
        Calculate next retry time based on error count.
        
        Args:
            error_count: Number of previous failures
        
        Returns:
            Datetime for next retry attempt
        """
        import random
        
        # Calculate base delay with exponential backoff
        delay = self.initial_delay * (self.backoff_multiplier ** (error_count - 1))
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to prevent thundering herd
        jitter_amount = delay * self.jitter
        delay = delay + random.uniform(-jitter_amount, jitter_amount)
        
        # Ensure positive delay
        delay = max(delay, 1)
        
        next_retry = datetime.utcnow() + timedelta(seconds=delay)
        
        logger.debug("retry_scheduled",
                    error_count=error_count,
                    delay_seconds=int(delay),
                    next_retry=next_retry.isoformat())
        
        return next_retry
    
    def should_retry(self, error_count: int) -> bool:
        """Check if we should retry based on attempt count."""
        return error_count < self.max_attempts
    
    def is_permanent_failure(self, error_message: str) -> bool:
        """
        Determine if an error is permanent (should not retry).
        
        Permanent failures:
        - 404 Not Found (resource doesn't exist)
        - 403 Forbidden (permission denied)
        - 400 Bad Request (invalid data)
        - ValidationError
        
        Temporary failures:
        - 429 Rate Limited
        - 500 Server Error
        - Network errors
        - Timeouts
        """
        permanent_patterns = [
            "404",
            "Not Found",
            "403",
            "Forbidden",
            "400",
            "Bad Request",
            "ValidationError",
            "Invalid",
            "does not exist"
        ]
        
        for pattern in permanent_patterns:
            if pattern.lower() in error_message.lower():
                logger.info("permanent_failure_detected",
                           error=error_message,
                           pattern=pattern)
                return True
        
        return False
```

**Test**:

```python
def test_retry_config_exponential_backoff():
    """Test exponential backoff calculation."""
    config = RetryConfig(
        initial_delay=60,
        backoff_multiplier=2.0,
        max_delay=3600
    )
    
    # First retry: ~60 seconds
    next_retry = config.calculate_next_retry(error_count=1)
    delay = (next_retry - datetime.utcnow()).total_seconds()
    assert 50 < delay < 70  # Allow for jitter
    
    # Second retry: ~120 seconds
    next_retry = config.calculate_next_retry(error_count=2)
    delay = (next_retry - datetime.utcnow()).total_seconds()
    assert 100 < delay < 140
    
    # Third retry: ~240 seconds
    next_retry = config.calculate_next_retry(error_count=3)
    delay = (next_retry - datetime.utcnow()).total_seconds()
    assert 200 < delay < 280

def test_retry_config_max_delay():
    """Test that delay is capped at maximum."""
    config = RetryConfig(
        initial_delay=60,
        backoff_multiplier=2.0,
        max_delay=300
    )
    
    # High error count should still cap at max_delay
    next_retry = config.calculate_next_retry(error_count=10)
    delay = (next_retry - datetime.utcnow()).total_seconds()
    assert delay <= 330  # max_delay + jitter

def test_retry_config_max_attempts():
    """Test max attempts check."""
    config = RetryConfig(max_attempts=5)
    
    assert config.should_retry(1) == True
    assert config.should_retry(4) == True
    assert config.should_retry(5) == False
    assert config.should_retry(10) == False

def test_retry_config_permanent_failure_detection():
    """Test permanent vs temporary failure detection."""
    config = RetryConfig()
    
    # Permanent failures
    assert config.is_permanent_failure("404 Not Found") == True
    assert config.is_permanent_failure("403 Forbidden") == True
    assert config.is_permanent_failure("ValidationError: Invalid username") == True
    
    # Temporary failures
    assert config.is_permanent_failure("429 Rate Limited") == False
    assert config.is_permanent_failure("500 Internal Server Error") == False
    assert config.is_permanent_failure("Connection timeout") == False
```

### 2. Failed Export Manager

#### 2.1 Failed Export Tracker

**Test**: Tracks and manages failed exports with dependencies

**File**: `src/gchat_mirror/exporters/discourse/failed_export_manager.py`

```python
# ABOUTME: Failed export tracking with dependency management
# ABOUTME: Handles retry scheduling and dependency blocking

import sqlite3
from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog

from gchat_mirror.exporters.discourse.retry_config import RetryConfig

logger = structlog.get_logger()

class FailedExportManager:
    """Manage failed exports and retry logic."""
    
    def __init__(self, state_conn: sqlite3.Connection,
                 retry_config: Optional[RetryConfig] = None):
        self.state_conn = state_conn
        self.retry_config = retry_config or RetryConfig()
    
    def record_failure(self, entity_type: str, entity_id: str,
                      operation: str, error_message: str,
                      blocked_by: Optional[str] = None) -> bool:
        """
        Record a failed export.
        
        Args:
            entity_type: Type of entity ('thread', 'message', 'reaction', etc.)
            entity_id: Entity ID
            operation: Operation that failed ('export', 'update', etc.)
            error_message: Error message
            blocked_by: Entity ID that blocks this one (e.g., thread blocks message)
        
        Returns:
            True if should retry, False if permanent failure
        """
        # Check if this is a permanent failure
        if self.retry_config.is_permanent_failure(error_message):
            logger.error("permanent_failure",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        error=error_message)
            
            # Don't add to retry queue
            return False
        
        # Get or create failed export record
        cursor = self.state_conn.execute("""
            SELECT error_count, first_attempt
            FROM failed_exports
            WHERE entity_type = ? AND entity_id = ? AND operation = ?
        """, (entity_type, entity_id, operation))
        
        existing = cursor.fetchone()
        
        if existing:
            error_count, first_attempt = existing
            error_count += 1
        else:
            error_count = 1
            first_attempt = datetime.utcnow()
        
        # Check if we should still retry
        if not self.retry_config.should_retry(error_count):
            logger.error("max_retries_exceeded",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        error_count=error_count)
            return False
        
        # Calculate next retry time
        next_retry = self.retry_config.calculate_next_retry(error_count)
        
        # Insert or update failed export
        self.state_conn.execute("""
            INSERT INTO failed_exports
            (entity_type, entity_id, operation, error_message, error_count,
             blocked_by, first_attempt, last_attempt, next_retry)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, operation)
            DO UPDATE SET
                error_message = excluded.error_message,
                error_count = excluded.error_count,
                blocked_by = excluded.blocked_by,
                last_attempt = excluded.last_attempt,
                next_retry = excluded.next_retry
        """, (entity_type, entity_id, operation, error_message, error_count,
              blocked_by, first_attempt, datetime.utcnow(), next_retry))
        
        self.state_conn.commit()
        
        logger.warning("export_failure_recorded",
                      entity_type=entity_type,
                      entity_id=entity_id,
                      error_count=error_count,
                      next_retry=next_retry.isoformat())
        
        return True
    
    def get_ready_retries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get failed exports ready for retry.
        
        Returns exports where:
        - next_retry is in the past
        - not blocked by another failed export
        
        Args:
            limit: Maximum number of retries to return
        
        Returns:
            List of failed export records
        """
        cursor = self.state_conn.execute("""
            SELECT 
                id,
                entity_type,
                entity_id,
                operation,
                error_message,
                error_count,
                blocked_by,
                first_attempt,
                last_attempt
            FROM failed_exports
            WHERE next_retry <= ?
            AND (
                blocked_by IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM failed_exports f2
                    WHERE f2.entity_id = failed_exports.blocked_by
                )
            )
            ORDER BY next_retry ASC
            LIMIT ?
        """, (datetime.utcnow(), limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row[0],
                'entity_type': row[1],
                'entity_id': row[2],
                'operation': row[3],
                'error_message': row[4],
                'error_count': row[5],
                'blocked_by': row[6],
                'first_attempt': row[7],
                'last_attempt': row[8]
            })
        
        return results
    
    def mark_success(self, entity_type: str, entity_id: str,
                    operation: str):
        """
        Mark a previously failed export as successful.
        
        This removes it from the failed exports table and unblocks
        any dependent exports.
        """
        self.state_conn.execute("""
            DELETE FROM failed_exports
            WHERE entity_type = ? AND entity_id = ? AND operation = ?
        """, (entity_type, entity_id, operation))
        
        self.state_conn.commit()
        
        logger.info("export_success",
                   entity_type=entity_type,
                   entity_id=entity_id)
        
        # Log any exports that are now unblocked
        cursor = self.state_conn.execute("""
            SELECT COUNT(*) FROM failed_exports
            WHERE blocked_by = ?
        """, (entity_id,))
        
        unblocked_count = cursor.fetchone()[0]
        if unblocked_count > 0:
            logger.info("exports_unblocked",
                       blocker_id=entity_id,
                       unblocked_count=unblocked_count)
    
    def is_blocked(self, entity_type: str, entity_id: str) -> bool:
        """
        Check if an entity's export is blocked by a failed dependency.
        
        Args:
            entity_type: Type of entity
            entity_id: Entity ID
        
        Returns:
            True if blocked, False otherwise
        """
        # Get the blocker entity ID based on type
        blocker_id = None
        
        if entity_type == 'message':
            # Messages are blocked by failed thread export
            cursor = self.state_conn.execute("""
                SELECT thread_id FROM messages WHERE id = ?
            """, (entity_id,))
            result = cursor.fetchone()
            if result:
                blocker_id = result[0]
                blocker_type = 'thread'
        
        elif entity_type == 'reaction':
            # Reactions are blocked by failed message export
            cursor = self.state_conn.execute("""
                SELECT message_id FROM reactions WHERE id = ?
            """, (entity_id,))
            result = cursor.fetchone()
            if result:
                blocker_id = result[0]
                blocker_type = 'message'
        
        else:
            # No blockers for threads, spaces, users
            return False
        
        if not blocker_id:
            return False
        
        # Check if blocker is in failed exports
        cursor = self.state_conn.execute("""
            SELECT 1 FROM failed_exports
            WHERE entity_type = ? AND entity_id = ?
        """, (blocker_type, blocker_id))
        
        is_blocked = cursor.fetchone() is not None
        
        if is_blocked:
            logger.debug("export_blocked",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        blocked_by_type=blocker_type,
                        blocked_by_id=blocker_id)
        
        return is_blocked
    
    def get_blocked_exports(self) -> List[Dict[str, Any]]:
        """
        Get all failed exports that are blocked by dependencies.
        
        Returns:
            List of blocked export records with blocker info
        """
        cursor = self.state_conn.execute("""
            SELECT 
                f1.entity_type,
                f1.entity_id,
                f1.operation,
                f1.error_message,
                f1.blocked_by,
                f2.entity_type as blocker_type,
                f2.error_message as blocker_error
            FROM failed_exports f1
            JOIN failed_exports f2 ON f1.blocked_by = f2.entity_id
            WHERE f1.blocked_by IS NOT NULL
            ORDER BY f1.first_attempt
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'entity_type': row[0],
                'entity_id': row[1],
                'operation': row[2],
                'error_message': row[3],
                'blocked_by_id': row[4],
                'blocked_by_type': row[5],
                'blocker_error': row[6]
            })
        
        return results
    
    def clear_all_failures(self):
        """Clear all failed exports (for testing or manual intervention)."""
        self.state_conn.execute("DELETE FROM failed_exports")
        self.state_conn.commit()
        logger.warning("all_failures_cleared")
    
    def force_retry(self, entity_type: str, entity_id: str):
        """
        Force immediate retry of a failed export.
        
        Sets next_retry to now and resets error_count.
        """
        self.state_conn.execute("""
            UPDATE failed_exports
            SET next_retry = ?,
                error_count = 1
            WHERE entity_type = ? AND entity_id = ?
        """, (datetime.utcnow(), entity_type, entity_id))
        
        self.state_conn.commit()
        
        logger.info("retry_forced",
                   entity_type=entity_type,
                   entity_id=entity_id)
```

**Test**:

```python
def test_failed_export_manager_records_failure(tmp_path):
    """Test recording a failed export."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    should_retry = manager.record_failure(
        entity_type='thread',
        entity_id='thread1',
        operation='export',
        error_message='Connection timeout'
    )
    
    assert should_retry == True
    
    # Verify record in database
    cursor = state_db.conn.execute("""
        SELECT error_count, error_message FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    row = cursor.fetchone()
    assert row[0] == 1
    assert 'timeout' in row[1]

def test_failed_export_manager_increments_error_count(tmp_path):
    """Test that repeated failures increment error count."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    # First failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 1')
    
    # Second failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 2')
    
    # Third failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 3')
    
    cursor = state_db.conn.execute("""
        SELECT error_count FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 3

def test_failed_export_manager_permanent_failure(tmp_path):
    """Test that permanent failures are not retried."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    should_retry = manager.record_failure(
        entity_type='thread',
        entity_id='thread1',
        operation='export',
        error_message='404 Not Found'
    )
    
    assert should_retry == False
    
    # Should not be in failed exports table
    cursor = state_db.conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 0

def test_failed_export_manager_max_retries(tmp_path):
    """Test that max retries stops retry attempts."""
    state_db = setup_test_state_db(tmp_path)
    config = RetryConfig(max_attempts=3)
    manager = FailedExportManager(state_db.conn, config)
    
    # First 3 attempts should allow retry
    assert manager.record_failure('thread', 'thread1', 'export', 'Error') == True
    assert manager.record_failure('thread', 'thread1', 'export', 'Error') == True
    assert manager.record_failure('thread', 'thread1', 'export', 'Error') == False

def test_failed_export_manager_get_ready_retries(tmp_path):
    """Test getting exports ready for retry."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    # Add a failed export with past retry time
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))  # Past date
    
    state_db.conn.commit()
    
    retries = manager.get_ready_retries()
    
    assert len(retries) == 1
    assert retries[0]['entity_id'] == 'thread1'

def test_failed_export_manager_blocked_exports(tmp_path):
    """Test that blocked exports are not returned for retry."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    # Failed thread (blocker)
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    
    # Failed message blocked by thread
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, 
         next_retry, blocked_by)
        VALUES ('message', 'msg1', 'export', 'Error', 1, ?, 'thread1')
    """, (datetime(2020, 1, 1),))
    
    state_db.conn.commit()
    
    retries = manager.get_ready_retries()
    
    # Only thread should be ready, message is blocked
    assert len(retries) == 1
    assert retries[0]['entity_type'] == 'thread'

def test_failed_export_manager_mark_success(tmp_path):
    """Test marking a failed export as successful."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    manager.record_failure('thread', 'thread1', 'export', 'Error')
    
    manager.mark_success('thread', 'thread1', 'export')
    
    # Should be removed from failed exports
    cursor = state_db.conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 0

def test_failed_export_manager_force_retry(tmp_path):
    """Test forcing immediate retry."""
    state_db = setup_test_state_db(tmp_path)
    manager = FailedExportManager(state_db.conn)
    
    # Create a failed export with future retry time
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 5, ?)
    """, (datetime(2099, 1, 1),))  # Far future
    
    state_db.conn.commit()
    
    # Force retry
    manager.force_retry('thread', 'thread1')
    
    # Should now be ready for retry
    retries = manager.get_ready_retries()
    assert len(retries) == 1
    assert retries[0]['error_count'] == 1  # Reset to 1
```

### 3. Retry Worker

#### 3.1 Retry Processor

**Test**: Processes ready retries

**File**: `src/gchat_mirror/exporters/discourse/retry_worker.py`

```python
# ABOUTME: Worker for processing failed export retries
# ABOUTME: Integrates with export pipeline to retry failed operations

import sqlite3
from typing import Callable, Dict, Any
import structlog

from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()

class RetryWorker:
    """Process failed export retries."""
    
    def __init__(self, 
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 failed_export_manager: FailedExportManager,
                 exporters: Dict[str, Callable]):
        """
        Initialize retry worker.
        
        Args:
            state_conn: State database connection
            chat_conn: Chat database connection
            failed_export_manager: Failed export manager
            exporters: Dict mapping entity_type to export function
                      e.g., {'thread': thread_exporter.export_thread}
        """
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.failed_manager = failed_export_manager
        self.exporters = exporters
    
    def process_retries(self, max_retries: int = 100) -> Dict[str, int]:
        """
        Process ready retries.
        
        Args:
            max_retries: Maximum number of retries to process
        
        Returns:
            Dict with counts: {'success': N, 'failed': M, 'skipped': K}
        """
        retries = self.failed_manager.get_ready_retries(limit=max_retries)
        
        if not retries:
            logger.debug("no_retries_ready")
            return {'success': 0, 'failed': 0, 'skipped': 0}
        
        logger.info("processing_retries", count=len(retries))
        
        stats = {'success': 0, 'failed': 0, 'skipped': 0}
        
        for retry in retries:
            entity_type = retry['entity_type']
            entity_id = retry['entity_id']
            operation = retry['operation']
            
            # Check if we have an exporter for this type
            exporter = self.exporters.get(entity_type)
            if not exporter:
                logger.error("no_exporter_for_type",
                           entity_type=entity_type)
                stats['skipped'] += 1
                continue
            
            # Attempt export
            try:
                logger.info("retrying_export",
                           entity_type=entity_type,
                           entity_id=entity_id,
                           attempt=retry['error_count'] + 1)
                
                result = exporter(entity_id)
                
                if result:
                    # Success!
                    self.failed_manager.mark_success(
                        entity_type,
                        entity_id,
                        operation
                    )
                    stats['success'] += 1
                    
                    logger.info("retry_succeeded",
                               entity_type=entity_type,
                               entity_id=entity_id)
                else:
                    # Export returned None/False
                    self.failed_manager.record_failure(
                        entity_type,
                        entity_id,
                        operation,
                        "Export returned no result"
                    )
                    stats['failed'] += 1
            
            except Exception as e:
                # Export raised exception
                logger.error("retry_failed",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            error=str(e))
                
                self.failed_manager.record_failure(
                    entity_type,
                    entity_id,
                    operation,
                    str(e)
                )
                stats['failed'] += 1
        
        logger.info("retry_processing_complete", **stats)
        
        return stats
```

**Test**:

```python
def test_retry_worker_processes_retries(tmp_path):
    """Test that retry worker processes ready retries."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    manager = FailedExportManager(state_db.conn)
    
    # Add a ready retry
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    state_db.conn.commit()
    
    # Mock exporter that succeeds
    mock_exporter = Mock(return_value={'success': True})
    
    worker = RetryWorker(
        state_db.conn,
        chat_db.conn,
        manager,
        {'thread': mock_exporter}
    )
    
    stats = worker.process_retries()
    
    assert stats['success'] == 1
    assert stats['failed'] == 0
    
    # Verify removed from failed exports
    cursor = state_db.conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_id = 'thread1'
    """)
    assert cursor.fetchone()[0] == 0

def test_retry_worker_handles_failure(tmp_path):
    """Test that retry worker handles failed retries."""
    state_db = setup_test_state_db(tmp_path)
    chat_db = setup_test_chat_db(tmp_path)
    
    manager = FailedExportManager(state_db.conn)
    
    # Add a ready retry
    state_db.conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    state_db.conn.commit()
    
    # Mock exporter that fails
    mock_exporter = Mock(side_effect=Exception("Still broken"))
    
    worker = RetryWorker(
        state_db.conn,
        chat_db.conn,
        manager,
        {'thread': mock_exporter}
    )
    
    stats = worker.process_retries()
    
    assert stats['success'] == 0
    assert stats['failed'] == 1
    
    # Verify error count incremented
    cursor = state_db.conn.execute("""
        SELECT error_count FROM failed_exports
        WHERE entity_id = 'thread1'
    """)
    assert cursor.fetchone()[0] == 2
```

## Completion Criteria

- [ ] Retry configuration with exponential backoff implemented
- [ ] Failed export manager tracks failures and dependencies
- [ ] Permanent failures detected and not retried
- [ ] Max retry attempts respected
- [ ] Dependency blocking works (thread → message → reaction)
- [ ] Retry worker processes ready retries
- [ ] Manual intervention tools (force retry, clear failures) work
- [ ] All tests pass

## Next Steps

After Phase 4.6, proceed to Phase 4.7: Complete Implementation and Integration
