# GChat Mirror - Master Implementation Plan

## Project Overview

**Purpose**: Mirror Google Chat data to local SQLite databases and export to Discourse, enabling use of Discourse’s superior interface while preserving complete Google Chat history.

**Target User**: Single user (Jesse) with admin access to both Google Chat and Discourse instances.

**Architecture**: Three independent components communicating via SQLite databases:

1. `gchat-sync` - Daemon that mirrors Google Chat → SQLite
1. Database layer - Two SQLite files (chat.db, attachments.db) with change notifications
1. Export clients - Standalone processes (starting with Discourse) that watch database and push to destinations

## Technology Stack

- **Language**: Python 3.11+
- **Package Management**: uv with pyproject.toml
- **HTTP Client**: httpx (for all HTTP operations)
- **Database**: SQLite with raw SQL (no ORM)
- **Logging**: structlog (structured JSON logging with systemd integration)
- **CLI**: click
- **Progress**: rich
- **Testing**: pytest with mocked API sessions
- **Auth**: Google Auth libraries + system keychain integration

## Key Design Principles

1. **Test-Driven Development (TDD)**: 
   - ALWAYS write failing tests first before implementing features
   - Follow the cycle: Write test → Watch it fail → Implement minimal code → Watch it pass → Refactor
   - All new features and bug fixes MUST follow this TDD cycle
   - Tests should be comprehensive and cover edge cases
   
2. **YAGNI**: Don't build features we don't need yet

3. **Idempotent operations**: Re-running exports should be safe

4. **Adaptive behavior**: Active spaces poll frequently, quiet ones less so

5. **Eager downloads**: Attachments, avatars, custom emoji downloaded immediately

6. **Complete fidelity**: Store everything from Google Chat, let exporters decide what to use

7. **Async/Concurrent Operations**: Use async tasks (asyncio) for I/O-bound operations like:
   - Parallel attachment downloads (from Google Chat API)
   - Concurrent space polling (reading from Google Chat API)
   - Multiple API requests (reading data)
   - **Note**: SQLite only supports a single writer at a time. Database writes must be serialized, not parallelized. Use async for API I/O, but coordinate database writes through a single connection or queue.

8. **Timestamp Format**: All timestamps MUST use ISO-8601 format in UTC
   - Store as: `YYYY-MM-DDTHH:MM:SS.mmmmmm+00:00` (Python's `datetime.isoformat()`)
   - Example: `2025-10-20T14:30:45.123456+00:00`
   - SQLite stores as TEXT, comparison works lexicographically
   - All datetime objects should be timezone-aware (UTC)

9. **Forward-Only Migrations**: 
   - Database migrations are forward-only
   - Do NOT implement `downgrade()` functions - they can be no-ops
   - Production systems never rollback migrations
   - If a migration needs to be undone, write a new forward migration

## File Layout (XDG Compliant)

```
~/.local/share/gchat-mirror/
├── sync/
│   ├── chat.db              # Main Google Chat mirror
│   └── attachments.db       # Binary attachment storage
└── exporters/
    └── discourse/
        └── state.db         # Discourse exporter state

~/.config/gchat-mirror/
├── sync/
│   └── config.toml          # Sync daemon config
└── exporters/
    └── discourse/
        └── config.toml      # Discourse exporter config

~/.cache/gchat-mirror/       # Logs, temporary files
```

## Repository Structure

```
gchat-mirror/
├── pyproject.toml           # Project config and dependencies
├── uv.lock                  # Locked dependencies
├── README.md
├── CLAUDE.md                # Development guidelines
├── src/
│   └── gchat_mirror/
│       ├── __init__.py
│       ├── sync/            # Sync daemon code
│       │   ├── __init__.py
│       │   ├── daemon.py
│       │   ├── google_client.py
│       │   ├── attachment_downloader.py
│       │   └── storage.py
│       ├── exporters/       # Export client modules
│       │   ├── __init__.py
│       │   └── discourse/
│       │       ├── __init__.py
│       │       ├── exporter.py
│       │       ├── discourse_client.py
│       │       └── storage.py
│       ├── common/          # Shared utilities
│       │   ├── __init__.py
│       │   ├── database.py
│       │   ├── notifications.py
│       │   └── logging.py
│       └── cli/             # CLI commands
│           ├── __init__.py
│           ├── main.py
│           ├── sync.py
│           └── export.py
├── migrations/              # Database migration scripts
│   ├── 001_initial_chat.py
│   ├── 002_initial_attachments.py
│   └── ...
├── tests/
│   ├── fixtures/            # Mock API responses
│   ├── test_sync/
│   ├── test_exporters/
│   └── test_common/
└── docs/
    ├── architecture.md
    ├── database_schema.md
    └── api_reference.md
```

## Development Phases

### Phase 1: Basic Sync (2-3 weeks)

**Goal**: Get messages from Google Chat into SQLite

- Project setup (uv, pyproject.toml, git repo)
- Database schemas (chat.db initial tables)
- Migration system (numbered scripts)
- Google Chat OAuth flow and credentials
- Basic API client for spaces and messages
- Simple sync loop (sequential, no attachments)
- CLI: `gchat-mirror sync start/stop/status`
- Tests with mocked API responses

### Phase 2: Complete Data Model (1-2 weeks)

**Goal**: Store all Google Chat data types with full fidelity

- Attachments (inline/chunked storage in attachments.db)
- Attachment downloader with parallel workers and rate limiting
- User avatars with history tracking
- Reactions and custom emoji
- Message revisions (edit history)
- Read receipts
- Notification queue system
- Export client registration

### Phase 3: Real-time Sync (2-3 weeks)

**Goal**: Robust, adaptive syncing with error handling

- Adaptive polling (10s for active, 5min for quiet spaces)
- Space discovery and access_denied handling
- Backfill command for historical data
- Error handling with exponential backoff
- Database integrity checks on startup
- Health check HTTP endpoint (:4981)
- Progress bars with rich library
- Comprehensive logging

### Phase 4: Discourse Exporter (3-4 weeks)

**Goal**: Export all data to Discourse with configurable mapping

- Discourse API client (httpx-based wrapper)
- User auto-creation and impersonation
- Space → Category/Chat mapping (3 modes: chat, private_messages, hybrid)
- Thread → Topic export with parallel processing
- Message export preserving edit history
- Attachment upload with URL caching
- Custom emoji upload on-demand
- Reaction export
- Read receipt sync (chat channels only)
- Failed export tracking and retry with dependent blocking
- State management (idempotent operations)

### Phase 5: Polish (2-3 weeks)

**Goal**: Production-ready system

- Comprehensive test coverage (unit + integration)
- Performance optimization
- Documentation (user guide, API reference)
- Bug fixes from real-world usage
- CLI refinements
- Enhanced monitoring and observability

## Critical Design Decisions

### Sync Strategy

- **Polling-based** (not Pub/Sub) with adaptive intervals
- **Sequential** space processing initially (until rate limits understood)
- **90 days** initial sync, then incremental
- **Backfill** older history via CLI command

### Data Storage

- **Two databases**: chat.db (metadata) + attachments.db (binary data)
- **Soft deletes**: Messages marked deleted but preserved
- **Complete history**: Message revisions, avatar changes, all reactions
- **Chunked storage**: Files >1MB split into 10MB chunks

### Attachment Downloads

- **Eager downloading**: All attachments downloaded immediately
- **Smart prioritization**: Recent messages first, then smallest files within those
- **Parallel workers**: CPU_count/2 concurrent downloads
- **Retry logic**: 5 attempts with exponential backoff, then quarantine

### Export Architecture

- **Standalone modules**: Export clients are independent processes
- **Notification-driven**: Watch notification_queue for changes
- **Idempotent**: Re-running exports is safe
- **Client registration**: Heartbeat system for cleanup coordination

### Discourse Mapping

- **Three modes**: chat, private_messages, hybrid (configurable)
- **Mode switching**: Start fresh exports, leave old data orphaned
- **Flat categories**: All spaces at top level
- **Thread = Topic**: Each Google Chat thread becomes a Discourse topic
- **Auto-create users**: On-demand user creation with impersonation

### Error Handling

- **Type-dependent**: 403/404 → immediate access_denied, others retry
- **Exponential backoff**: Progressive delays for temporary failures
- **Dependent blocking**: Failed messages block their reactions/replies
- **Pause on error**: Initially stops for manual intervention

## Testing Requirements

### Test Coverage

- All database operations (CRUD, migrations, integrity)
- Message parsing and transformation
- Topic title generation (edge cases: emoji-only, non-ASCII)
- Attachment storage (inline/chunked, integrity checks)
- Retry logic calculations
- Thread ordering and backfill
- Export idempotency
- Error handling paths

### Test Data Strategy

- Start minimal (single message/space)
- Progress to realistic complexity (dozens of spaces, hundreds of messages)
- Include edge cases: edits, deletions, reactions, long messages, rich content
- Mock API responses with fixtures
- Use recorded sessions for integration tests

## Configuration

### Sync Daemon Config (~/.config/gchat-mirror/sync/config.toml)

```toml
[auth]
credential_key = "gchat-sync"

[sync]
initial_sync_days = 90
active_space_poll_seconds = 10
quiet_space_poll_minutes = 5
download_workers = 4  # defaults to CPU/2

[monitoring]
health_check_port = 4981
```

### Discourse Exporter Config (~/.config/gchat-mirror/exporters/discourse/config.toml)

```toml
[discourse]
url = "https://discourse.example.com"
api_key = "${DISCOURSE_API_KEY}"  # Environment variable

[mapping]
dm_mode = "hybrid"  # or "chat" or "private_messages"
```

## CLI Interface

```bash
# Sync commands
gchat-mirror sync start              # Start sync daemon
gchat-mirror sync stop               # Stop sync daemon
gchat-mirror sync status             # Show sync status
gchat-mirror sync backfill --days 365                    # Backfill all spaces
gchat-mirror sync backfill --space-id SPACE_ID --days 90 # Backfill one space

# Export commands
gchat-mirror export discourse start  # Start Discourse exporter
gchat-mirror export discourse stop   # Stop Discourse exporter
gchat-mirror export discourse status # Show export status

# Client management
gchat-mirror clients list            # List registered export clients
gchat-mirror clients unregister ID   # Remove old export client

# Utility commands
gchat-mirror health                  # Query health check endpoint
gchat-mirror integrity-check         # Run database integrity checks
```

## Success Criteria

### Phase 1 Complete

- Can authenticate with Google Chat
- Fetches and stores messages from all accessible spaces
- Database schema created and populated
- Basic CLI works
- Tests passing

### Phase 2 Complete

- All data types stored (attachments, reactions, avatars, etc.)
- Attachment downloads working with parallel workers
- Edit history preserved
- Notification queue operational

### Phase 3 Complete

- Adaptive polling functioning
- Error handling robust
- Can backfill historical data
- Health check endpoint responding
- Progress bars showing during operations

### Phase 4 Complete

- Can create Discourse categories/chats for all spaces
- Messages exported with correct threading
- Edit history preserved in Discourse
- Attachments uploaded and linked
- All three mapping modes work
- Failed exports tracked and retried

### Phase 5 Complete

- Comprehensive test coverage
- Documentation complete
- No known critical bugs
- Performance acceptable for daily use
- Ready for production use

## Next Steps

See detailed phase specifications:

- Phase 1: Basic Sync (separate document)
- Phase 2: Complete Data Model (separate document)
- Phase 3: Real-time Sync (separate document)
- Phase 4: Discourse Exporter (separate document)
- Phase 5: Polish (separate document)

Each phase document contains:

- Detailed task breakdown
- Database schema definitions
- Test requirements
- Acceptance criteria
- Implementation notes
 