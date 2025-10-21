# Phase 5: Polish - Detailed Specification

## Goal

Production-ready system with comprehensive tests, performance optimizations, complete documentation, and real-world hardening.

## Duration

2-3 weeks

## Prerequisites

- Phases 1-4 complete
- Basic system working end-to-end

## Tasks

### 1. Comprehensive Test Coverage

#### 1.1 Unit Test Audit

**Test**: All modules have unit tests with >80% coverage

**Action Items**:

1. Run coverage analysis:
   ```bash
   uv run pytest --cov=src/gchat_mirror --cov-report=html --cov-report=term
   ```

2. Identify untested code paths

3. Write missing unit tests for:
   - Edge cases in message parsing
   - Error handling paths
   - Boundary conditions (empty strings, null values, max sizes)
   - Retry logic corner cases
   - Rate limit handling

4. Test all database migrations:
   - Forward migrations
   - Schema validation after each migration
   - Data integrity after migrations
   - Migration sequence (001, 002, ..., N)

**Files to focus on**:
- `src/gchat_mirror/sync/google_client.py` - API edge cases
- `src/gchat_mirror/sync/storage.py` - Database operations
- `src/gchat_mirror/exporters/discourse/discourse_client.py` - API client
- `src/gchat_mirror/common/retry.py` - Backoff calculations

**Test Examples**:

```python
def test_message_with_null_text():
    """Test handling message with null text field."""
    storage = SyncStorage(conn)
    message = {
        'name': 'msg1',
        'text': None,  # API sometimes returns null
        'sender': {'name': 'user1'}
    }
    storage.insert_message(message)
    # Should not crash

def test_empty_space_name():
    """Test space with empty display name."""
    storage = SyncStorage(conn)
    space = {
        'name': 'spaces/123',
        'displayName': '',  # Empty name
        'type': 'SPACE'
    }
    storage.upsert_space(space)
    # Should use ID as fallback

def test_retry_backoff_max_delay():
    """Test that backoff caps at max delay."""
    config = RetryConfig(initial_delay=1, max_delay=10, backoff_factor=2)
    # After many attempts, should cap at max_delay
    assert config.get_delay(10) == 10
    assert config.get_delay(100) == 10
```

#### 1.2 Integration Tests

**Test**: End-to-end scenarios work correctly

**Test Scenarios**:

1. **Full sync workflow**:
   - Start daemon
   - Discover spaces
   - Sync messages
   - Download attachments
   - Update activity metrics
   - Stop cleanly

2. **Export workflow**:
   - Start exporter
   - Create users
   - Create categories/channels
   - Export threads
   - Export messages
   - Handle failures

3. **Error recovery**:
   - Network failure during sync
   - Discourse API unavailable
   - Database locked
   - Disk full simulation

4. **Mode switching**:
   - Export in chat mode
   - Switch to hybrid mode
   - Verify old exports orphaned
   - New exports use correct mode

**File**: `tests/test_integration/test_full_workflow.py`

```python
@pytest.mark.integration
def test_full_sync_and_export(tmp_path, httpx_mock):
    """Test complete workflow from sync to export."""
    # Setup mocked APIs for both Google Chat and Discourse
    # ... mock setup ...
    
    # 1. Run sync
    sync_daemon = SyncDaemon(tmp_path, config)
    sync_daemon.start()
    # ... verify sync completed ...
    
    # 2. Run export
    exporter = DiscourseExporter(tmp_path, export_config)
    exporter.start()
    # ... verify export completed ...
    
    # 3. Verify data consistency
    # Check that all messages made it to Discourse
    # Check mappings are correct
    # Check attachments uploaded
```

### 2. Performance Optimization

#### 2.1 Database Performance

**Test**: Queries complete in reasonable time

**Optimizations**:

1. **Add missing indexes**:
   ```python
   # Check query plans
   EXPLAIN QUERY PLAN SELECT ...
   
   # Add indexes where table scans found
   CREATE INDEX idx_messages_space_time 
   ON messages(space_id, create_time)
   ```

2. **Batch operations**:
   ```python
   # Before: Individual inserts
   for message in messages:
       storage.insert_message(message)
   
   # After: Batch insert
   storage.insert_messages_batch(messages)
   ```

3. **VACUUM and ANALYZE** periodically to maintain query performance

4. **Write serialization**: Remember that SQLite only supports a single writer at a time. All database writes must be serialized through a single connection. Use WAL (Write-Ahead Logging) mode for better read concurrency:
   ```python
   conn.execute("PRAGMA journal_mode=WAL")
   ```

**File**: Update `src/gchat_mirror/common/database.py`

```python
def optimize(self):
    """Run database optimization."""
    logger.info("optimizing_database")
    
    self.conn.execute("VACUUM")
    self.conn.execute("ANALYZE")
    
    logger.info("optimization_complete")

def get_query_stats(self) -> Dict[str, Any]:
    """Get database statistics."""
    stats = {}
    
    # Table sizes
    cursor = self.conn.execute("""
        SELECT name, 
               (SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name=name) as index_count
        FROM sqlite_master WHERE type='table'
    """)
    # ... collect stats ...
    
    return stats
```

#### 2.2 API Rate Limiting

**Test**: Respects rate limits without excessive delays

**Optimizations**:

1. **Adaptive rate limiting**:
   - Track successful request rate
   - Reduce request frequency if getting 429s
   - Increase gradually when successful

2. **Request batching where possible**:
   - Google Chat API: Use pageSize effectively
   - Discourse API: Batch user creation if supported

3. **Parallel processing** (for API I/O operations only):
   - Multiple spaces can be polled in parallel (reading from API)
   - Attachment downloads in parallel (reading from API)
   - Export API calls in parallel (writing to Discourse)
   - **Important**: Database writes must be serialized due to SQLite's single-writer limitation. Use async for API I/O, then write to database sequentially or use a write queue.

#### 2.3 Memory Usage

**Test**: Memory usage stays bounded

**Optimizations**:

1. **Stream large files** instead of loading into memory
2. **Process messages in batches** rather than loading all
3. **Clear caches** periodically
4. **Monitor memory usage** in health endpoint

### 3. Documentation

#### 3.1 User Guide

**File**: `docs/user-guide.md`

**Contents**:

1. **Installation**:
   - System requirements
   - Installing uv
   - Cloning repository
   - Running setup

2. **Google Chat Setup**:
   - Creating Google Cloud project
   - Enabling Chat API
   - Creating OAuth credentials
   - Downloading client_secrets.json

3. **Initial Sync**:
   - Running first sync
   - OAuth authorization flow
   - Monitoring progress
   - Troubleshooting common issues

4. **Configuration**:
   - Config file format
   - Environment variables
   - Available options
   - Examples

5. **Discourse Setup**:
   - Prerequisites (Discourse version, plugins)
   - Getting API key
   - Configuring exporter
   - Choosing mapping mode

6. **Running Exporters**:
   - Starting Discourse exporter
   - Monitoring export progress
   - Handling failures
   - Restarting exports

7. **Maintenance**:
   - Backfilling historical data
   - Integrity checks
   - Database optimization
   - Log rotation

8. **Troubleshooting**:
   - Common errors and solutions
   - Debug logging
   - Health checks
   - Getting help

#### 3.2 API Reference

**File**: `docs/api-reference.md`

**Contents**:

1. **Database Schemas**:
   - chat.db tables and columns
   - attachments.db structure
   - Exporter state.db structure
   - Foreign key relationships

2. **Python APIs**:
   - SyncStorage methods
   - GoogleChatClient methods
   - DiscourseClient methods
   - Configuration functions

3. **CLI Commands**:
   - Full command reference
   - Options and arguments
   - Examples
   - Exit codes

4. **Health Check API**:
   - Endpoints
   - Response formats
   - Metrics available

#### 3.3 Developer Guide

**File**: `docs/developer-guide.md`

**Contents**:

1. **Architecture Overview**:
   - Component diagram
   - Data flow
   - Design decisions

2. **Development Setup**:
   - Installing dev dependencies
   - Running tests
   - Code formatting
   - Pre-commit hooks

3. **Testing**:
   - Test structure
   - Mocking strategies
   - Fixture usage
   - Running specific tests

4. **Adding Features**:
   - Creating migrations
   - Adding API methods
   - Writing tests
   - Documenting changes

5. **Contributing**:
   - Code style
   - Pull request process
   - Release process

### 4. Bug Fixes from Real-World Usage

#### 4.1 Systematic Testing

**Process**:

1. **Deploy to test environment**
2. **Run against real Google Chat workspace**
3. **Monitor for errors** in logs
4. **Document unexpected behavior**
5. **Write reproduction test**
6. **Fix and verify**

**Common Issues to Watch For**:

1. **Unicode handling**:
   - Emoji in message text
   - Non-ASCII characters in names
   - RTL text
   - Zero-width characters

2. **Large messages**:
   - Very long messages
   - Messages with many attachments
   - Threads with hundreds of messages

3. **Edge cases**:
   - Deleted users
   - Deleted spaces
   - Messages edited immediately after sending
   - Reactions on deleted messages

4. **Timing issues**:
   - Clock skew between systems
   - Timestamp parsing across timezones
   - Message ordering when syncing multiple spaces concurrently
   - **Note**: SQLite's single-writer constraint prevents database-level race conditions, but API timing issues can still occur

5. **API quirks**:
   - Undocumented Google Chat API behavior
   - Discourse API version differences
   - Authentication token expiration

#### 4.2 Error Handling Improvements

**File**: Update error handling across codebase

```python
# Add specific exception types
class GChatMirrorError(Exception):
    """Base exception for gchat-mirror."""
    pass

class SyncError(GChatMirrorError):
    """Sync-related error."""
    pass

class ExportError(GChatMirrorError):
    """Export-related error."""
    pass

# Improve error messages
try:
    result = api_call()
except httpx.HTTPStatusError as e:
    logger.error("api_error",
                status=e.response.status_code,
                body=e.response.text[:500],  # Include response for debugging
                url=e.request.url)
    raise SyncError(f"API request failed: {e}") from e
```

### 5. CLI Refinements

#### 5.1 Improved Output

**Enhancements**:

1. **Better progress indicators**:
   - Show current space being synced
   - Messages per second rate
   - ETA for completion

2. **Colored output** for errors/warnings

3. **Summary statistics** after operations

4. **Interactive mode** for configuration

**File**: Update `src/gchat_mirror/cli/sync.py`

```python
@sync.command()
@click.option('--watch', is_flag=True, help='Watch mode with live updates')
@click.pass_context
def start(ctx, watch: bool):
    """Start the sync daemon."""
    # ... existing code ...
    
    if watch:
        # Live monitoring mode
        from rich.live import Live
        from rich.table import Table
        
        with Live(generate_status_table(), refresh_per_second=1) as live:
            # Update table every second
            while daemon.running:
                live.update(generate_status_table())
                time.sleep(1)
```

#### 5.2 Configuration Wizard

**File**: New `src/gchat_mirror/cli/setup.py`

```python
@click.command()
@click.pass_context
def setup(ctx):
    """Interactive setup wizard."""
    from rich.prompt import Prompt, Confirm
    
    click.echo("GChat Mirror Setup Wizard\n")
    
    # Check for client_secrets.json
    if not Path("client_secrets.json").exists():
        click.echo("❌ client_secrets.json not found")
        click.echo("Please download OAuth credentials from Google Cloud Console")
        return
    
    # Create config
    config = {}
    
    config['sync'] = {
        'initial_sync_days': Prompt.ask(
            "Days of history to sync initially",
            default="90"
        )
    }
    
    if Confirm.ask("Set up Discourse exporter now?"):
        config['discourse'] = {
            'url': Prompt.ask("Discourse URL"),
            'api_key': Prompt.ask("API Key", password=True),
            'mapping_mode': Prompt.ask(
                "Mapping mode",
                choices=["chat", "private_messages", "hybrid"],
                default="hybrid"
            )
        }
    
    # Save config
    config_dir = ctx.obj['config_dir'] / 'sync'
    config_dir.mkdir(parents=True, exist_ok=True)
    
    with open(config_dir / 'config.toml', 'w') as f:
        toml.dump(config, f)
    
    click.echo("\n✓ Configuration saved!")
    click.echo("\nNext steps:")
    click.echo("  1. Run: gchat-mirror sync start")
    click.echo("  2. Complete OAuth authorization in browser")
```

### 6. Enhanced Monitoring and Observability

#### 6.1 Structured Metrics

**File**: New `src/gchat_mirror/common/metrics.py`

```python
# ABOUTME: Metrics collection and reporting
# ABOUTME: Tracks operation counts, timings, and errors

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict
import structlog

logger = structlog.get_logger()

@dataclass
class Metrics:
    """Application metrics."""
    
    # Sync metrics
    spaces_synced: int = 0
    messages_synced: int = 0
    attachments_downloaded: int = 0
    sync_errors: int = 0
    
    # Export metrics  
    topics_created: int = 0
    posts_created: int = 0
    export_errors: int = 0
    
    # Timing
    sync_duration_seconds: float = 0.0
    export_duration_seconds: float = 0.0
    
    # Rates (messages per second, etc.)
    sync_rate: float = 0.0
    export_rate: float = 0.0
    
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        for field_name, value in self.__dict__.items():
            if isinstance(value, (int, float)):
                metric_name = f"gchat_mirror_{field_name}"
                lines.append(f"# TYPE {metric_name} gauge")
                lines.append(f"{metric_name} {value}")
        
        return "\n".join(lines)
```

#### 6.2 Alerting Integration

**File**: New `src/gchat_mirror/common/alerts.py`

```python
# ABOUTME: Alert notifications for critical errors
# ABOUTME: Supports email, Slack, and webhook notifications

def send_alert(title: str, message: str, severity: str = "warning"):
    """Send an alert notification."""
    # Implementation depends on configured alert channel
    logger.error("alert", title=title, message=message, severity=severity)
    
    # Could integrate with:
    # - Email (SMTP)
    # - Slack webhooks
    # - PagerDuty
    # - Custom webhooks
```

### 7. Production Readiness Checklist

#### 7.1 Security Review

- [ ] Credentials stored securely (keychain)
- [ ] API keys not in logs
- [ ] File permissions appropriate
- [ ] SQL injection prevention (parameterized queries)
- [ ] Input validation on all user input
- [ ] Rate limiting prevents abuse

#### 7.2 Reliability

- [ ] Graceful shutdown on SIGTERM
- [ ] Automatic recovery from crashes
- [ ] Transaction boundaries correct
- [ ] No data loss on unexpected shutdown
- [ ] Idempotent operations
- [ ] Failed operations retry correctly

#### 7.3 Observability

- [ ] All operations logged
- [ ] Log levels appropriate
- [ ] Metrics exported
- [ ] Health check responds
- [ ] Status visible in CLI
- [ ] Errors include context

#### 7.4 Documentation

- [ ] User guide complete
- [ ] API reference complete
- [ ] Developer guide complete
- [ ] README up to date
- [ ] Installation tested
- [ ] Examples work

#### 7.5 Testing

- [ ] Unit test coverage >80%
- [ ] Integration tests pass
- [ ] Manual testing completed
- [ ] Performance acceptable
- [ ] Memory leaks checked
- [ ] Load testing done (if applicable)

## Completion Criteria

- [ ] Test coverage >80% on all modules
- [ ] Integration tests cover main workflows
- [ ] Performance optimized (queries fast, memory bounded)
- [ ] User guide written and tested
- [ ] API reference complete
- [ ] Developer guide written
- [ ] Real-world testing completed
- [ ] All known bugs fixed
- [ ] CLI refined with good UX
- [ ] Monitoring and metrics working
- [ ] Security review passed
- [ ] Production readiness checklist complete
- [ ] No critical or high-priority bugs

## Success Criteria

Phase 5 is complete when:

1. **Testing**: Comprehensive test suite with good coverage
2. **Performance**: Acceptable performance for daily use
3. **Documentation**: Complete user and developer docs
4. **Reliability**: Handles errors gracefully, no data loss
5. **Usability**: CLI is intuitive and helpful
6. **Monitoring**: Can observe system health and metrics
7. **Production-ready**: Passes security and reliability review

## Deployment

After Phase 5 completion, system is ready for production use:

1. Deploy to production environment
2. Configure monitoring/alerting
3. Run initial sync
4. Start exporters
5. Monitor for issues
6. Iterate based on real-world usage

## Future Enhancements

Potential future phases (not required for initial release):

- Additional export clients (Slack, Discord, Matrix)
- Web UI for configuration and monitoring
- Multi-tenancy support
- Cloud deployment (Docker, Kubernetes)
- Incremental export updates (real-time sync to Discourse)
- Search functionality
- Analytics and reporting
