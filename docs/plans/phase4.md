# Phase 4: Discourse Exporter

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

This phase is split into 7 sub-phases for clarity and manageability.

## Sub-Phases

### [Phase 4.1: Exporter Database Schema](./phase4-1.md)
**Duration**: 1 day

Create the database schema for tracking Discourse export state, mappings, and failures.

**Key Deliverables**:
- Export mappings table (Google Chat ID → Discourse ID)
- Failed exports table (retry tracking with exponential backoff)
- Export progress table (per-space progress tracking)
- Exporter state table (configuration and global state)
- Migration system integration

### [Phase 4.2: Discourse API Client](./phase4-2.md)
**Duration**: 2-3 days

Implement a comprehensive Discourse API client for creating and managing content.

**Key Deliverables**:
- Category creation and management
- Topic and post creation with backdating
- User creation with auto-generated passwords
- Chat channel support (requires Discourse Chat plugin)
- Private message creation
- File upload with proper handling
- Rate limiting (429) handling

### [Phase 4.3: User Management](./phase4-3.md)
**Duration**: 1 day

Implement user mapping and auto-creation from Google Chat users to Discourse users.

**Key Deliverables**:
- Username generation from display names
- Auto-creation of users on-demand
- Mapping cache (Google Chat ID → Discourse username)
- Uniqueness handling with counters
- Email fallback for short names

### [Phase 4.4: Space to Discourse Mapping](./phase4-4.md)
**Duration**: 1 day

Map Google Chat spaces to appropriate Discourse structures based on configuration mode.

**Key Deliverables**:
- Chat mode implementation (all spaces → chat channels)
- Private messages mode (DMs → PMs, spaces → categories)
- Hybrid mode (DMs → PMs, spaces → chat channels)
- Mapping storage and caching
- Participant tracking for DMs

### [Phase 4.5: Thread and Message Export](./phase4-5.md)
**Duration**: 1 week

Export Google Chat threads and messages to Discourse with proper threading, markdown conversion, edit history, attachments, and reactions.

**Key Deliverables**:
- Thread title generation from first messages
- Topic/post creation with proper threading
- Markdown conversion (GChat → Discourse)
- Edit history preservation
- Attachment handling with URL caching
- Reaction export

### [Phase 4.6: Failed Export Tracking and Retry](./phase4-6.md)
**Duration**: 3-4 days

Implement robust error handling for Discourse exports with dependency tracking, exponential backoff, and manual intervention capabilities.

**Key Deliverables**:
- Retry configuration with exponential backoff
- Failed export tracking with dependencies
- Permanent vs temporary failure detection
- Dependency blocking (thread → message → reaction)
- Retry worker for processing failed exports
- Manual intervention tools (force retry, clear failures)

### [Phase 4.7: Complete Implementation and Integration](./phase4-7.md)
**Duration**: 1 week

Complete the Discourse exporter with full message export, attachment caching, emoji support, state management, and CLI integration.

**Key Deliverables**:
- Attachment upload and URL caching
- Complete message exporter with parallel processing
- Reaction exporter
- Export state manager (progress tracking)
- CLI integration (start, status, retry commands)
- End-to-end integration tests

## Implementation Order

Follow the phases in numeric order:
1. Start with Phase 4.1 (database schema)
2. Proceed through 4.2-4.4 (infrastructure)
3. Implement 4.5-4.6 (core export logic)
4. Complete with 4.7 (integration)

Each phase builds on the previous phases, so the order is important.

## Overall Completion Criteria

- [ ] All sub-phases complete
- [ ] Exporter state database created and migrated
- [ ] Discourse API client fully functional
- [ ] User auto-creation working
- [ ] All three mapping modes functional
- [ ] Threads exported as topics/PMs/chat threads
- [ ] Messages exported with threading
- [ ] Edit history preserved
- [ ] Attachments uploaded with caching
- [ ] Reactions exported
- [ ] Failed exports tracked and retried with exponential backoff
- [ ] CLI commands working (start, status, retry)
- [ ] Export progress tracked per space
- [ ] All integration tests pass
- [ ] End-to-end export verified

## Architecture Notes

### Component Structure

```
src/gchat_mirror/exporters/discourse/
├── discourse_client.py          # API client
├── user_mapper.py               # User management
├── space_mapper.py              # Space mapping
├── thread_title.py              # Title generation
├── markdown_converter.py        # Message transformation
├── thread_exporter.py           # Thread export
├── message_exporter.py          # Message export
├── reaction_exporter.py         # Reaction export
├── attachment_cache.py          # Attachment caching
├── retry_config.py              # Retry configuration
├── failed_export_manager.py    # Failed export tracking
├── retry_worker.py              # Retry processing
└── export_state.py              # Progress tracking
```

### Database Files

- **chat.db**: Google Chat data (from Phase 1-3)
- **attachments.db**: Binary attachment data
- **state.db**: Exporter state (mappings, failures, progress)

### Data Flow

1. **Notification Queue** → Exporter daemon
2. **Space** → Space Mapper → Category/Chat Channel/PM setup
3. **Thread** → Thread Exporter → Topic/PM
4. **Message** → Message Exporter → Post/Chat Message
5. **Attachment** → Attachment Cache → Upload → URL
6. **Reaction** → Reaction Exporter → Post reaction
7. **Failure** → Failed Export Manager → Retry Worker → Re-export

### Dependency Chain

```
Space
  └─ Thread
       └─ Message
            └─ Reaction

User (created on-demand)
```

Failed exports block dependent exports:
- Failed thread blocks all its messages
- Failed message blocks all its reactions

### Mapping Modes Comparison

| Entity | Chat Mode | Private Messages Mode | Hybrid Mode (Default) |
|--------|-----------|----------------------|----------------------|
| Regular Space | Chat Channel | Category | Chat Channel |
| DM | Chat Channel | Private Message | Private Message |
| Thread | (Flat messages) | Topic | (Flat messages / PM) |
| Message | Chat Message | Post | Chat Message / PM Post |

### Configuration

Set mapping mode in exporter state database:

```python
conn.execute("""
    UPDATE exporter_state 
    SET value = 'hybrid'
    WHERE key = 'mapping_mode'
""")
```

Or via CLI:
```bash
gchat-mirror export start --mapping-mode hybrid
```

## Testing Strategy

### Unit Tests
- Test each component in isolation with mocked dependencies
- Mock Discourse API with httpx_mock
- Use pytest fixtures for test databases

### Integration Tests
- Test complete export flow with real databases
- Mock only Discourse API
- Verify mappings, dependencies, retries

### End-to-End Tests
- Test against real Discourse instance (optional)
- Verify complete export including attachments
- Check backdating, edit history, reactions

## Common Issues and Solutions

### Issue: Rate Limiting

**Solution**: DiscourseRateLimitError is caught by retry logic with exponential backoff

### Issue: Attachment Upload Failures

**Solution**: Attachments cached separately, failed uploads don't block message export

### Issue: Username Conflicts

**Solution**: Automatic counter suffix (alice_smith_1, alice_smith_2, etc.)

### Issue: Orphaned Exports

**Solution**: Dependency tracking prevents messages from being exported before their thread

### Issue: Partial Failures

**Solution**: Each entity tracked independently, can resume from any point

## Monitoring and Observability

### Logging

All components use structlog with structured JSON logs:

```python
logger.info("message_exported",
           message_id=message_id,
           post_id=post_id,
           thread_id=thread_id)
```

### Progress Tracking

Query export progress:

```bash
gchat-mirror export status
```

Shows:
- Spaces exported (completed/total)
- Threads, messages, attachments, reactions counts
- Failed exports count
- Currently processing space

### Metrics

Track:
- Export rate (messages/minute)
- Failure rate by entity type
- Retry queue depth
- API rate limit hits

## Next Steps

After Phase 4 is complete, proceed to [Phase 5: Polish and Production Readiness](./phase5.md).
