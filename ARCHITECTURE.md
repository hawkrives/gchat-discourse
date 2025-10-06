# Architecture and Design

## Overview

The gchat-discourse sync service provides bidirectional synchronization between Google Chat and Discourse. This document explains the architecture, design decisions, and data flow.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Sync Service (main.py)                    │
│                                                               │
│  ┌────────────────────┐       ┌─────────────────────────┐   │
│  │  Periodic Scheduler │       │  Webhook Listener       │   │
│  │  (schedule)         │       │  (Flask/5000)          │   │
│  └─────────┬──────────┘       └──────────┬──────────────┘   │
│            │                               │                  │
│            v                               v                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │            Sync Logic Coordinators                      │  │
│  │  ┌──────────────────────┐  ┌────────────────────────┐ │  │
│  │  │  GChat → Discourse   │  │  Discourse → GChat     │ │  │
│  │  └──────────────────────┘  └────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────┐       ┌─────────────────────────┐   │
│  │  Google Chat Client│       │  Discourse Client       │   │
│  │  (OAuth 2.0)       │       │  (API Key)             │   │
│  └─────────┬──────────┘       └──────────┬──────────────┘   │
└────────────┼───────────────────────────────┼─────────────────┘
             │                               │
             v                               v
    ┌────────────────┐              ┌────────────────┐
    │  Google Chat   │              │   Discourse    │
    │  API           │              │   REST API     │
    └────────────────┘              └────────────────┘

         ┌─────────────────────────┐
         │  SQLite Database        │
         │  (sync_db.sqlite)       │
         │  - Mappings             │
         │  - State                │
         └─────────────────────────┘
```

## Component Responsibilities

### Main Service (`main.py`)
- Initializes all components
- Coordinates initial sync
- Manages periodic catch-up sync
- Routes webhook events to handlers

### API Clients

#### Google Chat Client (`google_chat_client.py`)
- OAuth 2.0 authentication flow
- Manages refresh tokens
- CRUD operations for spaces, threads, and messages
- Error handling and retries

#### Discourse Client (`discourse_client.py`)
- API key authentication
- CRUD operations for categories, topics, and posts
- HTTP request handling
- Response parsing

### Sync Modules

#### GChat to Discourse (`sync_gchat_to_discourse.py`)
- Fetches Google Chat spaces, threads, and messages
- Creates corresponding Discourse categories, topics, and posts
- Stores mappings in database
- Handles updates and edits

#### Discourse to GChat (`sync_discourse_to_gchat.py`)
- Receives webhook events from Discourse
- Creates corresponding Google Chat messages
- Prevents infinite loops
- Handles topic creation in Discourse

### State Management

#### Database (`db.py`)
- Stores bidirectional mappings
- Tracks sync timestamps
- Provides query interface
- SQLite for simplicity and portability

## Data Mappings

### Entity Mapping

| Google Chat | Discourse | Description |
|-------------|-----------|-------------|
| Space (Room) | Category | Container for group conversations |
| Space (DM) | Chat Channel | Direct message conversations |
| Thread | Topic | Conversation thread in a room |
| Message (Room) | Post | Individual message/post in a room |
| Message (DM) | Chat Message | Individual message in a DM |
| User | User | User accounts with proper attribution |

### Database Schema

```sql
-- Space to Category mapping (for rooms)
CREATE TABLE space_to_category (
    google_space_id TEXT PRIMARY KEY,
    discourse_category_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Thread to Topic mapping (for room threads)
CREATE TABLE thread_to_topic (
    google_thread_id TEXT PRIMARY KEY,
    discourse_topic_id INTEGER NOT NULL,
    google_space_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (google_space_id) REFERENCES space_to_category(google_space_id)
);

-- Message to Post mapping (for room messages)
CREATE TABLE message_to_post (
    google_message_id TEXT PRIMARY KEY,
    discourse_post_id INTEGER NOT NULL,
    google_thread_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (google_thread_id) REFERENCES thread_to_topic(google_thread_id)
);

-- User mapping (Google Chat users to Discourse users)
CREATE TABLE user_mapping (
    google_user_id TEXT PRIMARY KEY,
    google_user_name TEXT NOT NULL,
    google_user_email TEXT,
    discourse_username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- DM Space to Chat Channel mapping
CREATE TABLE dm_space_to_chat_channel (
    google_space_id TEXT PRIMARY KEY,
    discourse_chat_channel_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- DM Message to Chat Message mapping
CREATE TABLE dm_message_to_chat_message (
    google_message_id TEXT PRIMARY KEY,
    discourse_chat_message_id INTEGER NOT NULL,
    google_space_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (google_space_id) REFERENCES dm_space_to_chat_channel(google_space_id)
);

-- Sync state tracking
CREATE TABLE sync_state (
    space_id TEXT PRIMARY KEY,
    last_sync_timestamp TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Synchronization Flows

### Space Type Detection

The sync service automatically detects the type of Google Chat space:
- **Room spaces** (type = 'ROOM' or 'SPACE'): Synced to Discourse categories/topics
- **DM spaces** (type = 'DIRECT_MESSAGE' or 'DM'): Synced to Discourse chat channels

### User Management

For proper message attribution, the service:
1. Extracts sender information from each Google Chat message
2. Creates a corresponding Discourse user if one doesn't exist
3. Generates usernames in the format `gchat_<displayname>` (e.g., `gchat_john_doe`)
4. Uses fake email addresses for sync users (e.g., `gchat_john_doe@gchat-sync.local`)
5. Stores mappings in the `user_mapping` table
6. Posts messages as the actual user using Discourse's API user impersonation feature

**User Impersonation**: Messages are posted with proper user attribution by using the admin API key with the `Api-Username` header. This allows the sync service to post content as any user without requiring individual API keys for each user. When creating a post, topic, or chat message, the service sets `Api-Username` to the target user's username, and Discourse attributes the content to that user.

### Initial Sync (Google Chat → Discourse)

1. Load space mappings from config
2. For each mapped space:
   - Fetch space details
   - Detect space type (Room vs DM)
   - **If Room space**:
     - Create/verify Discourse category
     - Store mapping in database
     - List all threads and messages
     - Create topics and posts
   - **If DM space**:
     - Get space members
     - Create Discourse users for all members
     - Create Discourse chat channel
     - Store mapping in database
     - List all messages
     - Create chat messages with attribution
3. Store all mappings

### Real-time Sync (Discourse → Google Chat)

1. Discourse webhook fires on post creation
2. Webhook listener receives POST request
3. Handler checks for loop conditions:
   - Is post by API user? → Skip
   - Does post already have mapping? → Skip
4. Look up corresponding Google Chat thread
5. Create message in Google Chat
6. Store mapping

### Periodic Catch-up Sync

1. Timer triggers every N minutes
2. For each space:
   - Get last sync timestamp from database
   - Fetch messages since timestamp
   - Sync new messages to Discourse
   - Update timestamp

## Loop Prevention

Critical to avoid infinite sync loops:

### Strategy 1: User Detection
- Check if Discourse post username matches API username
- Skip syncing posts created by the service itself

### Strategy 2: Mapping Check
- Before syncing, check if entity already has a mapping
- If mapping exists, content originated from other platform

### Strategy 3: Transaction IDs
- Could add transaction IDs to metadata (future enhancement)
- Track sync operations to avoid re-processing

## Configuration

Configuration is centralized in `config.yaml`:

```yaml
discourse:
  url: "http://localhost:8888"
  api_key: "SECRET"
  api_username: "sync_bot"

google:
  credentials_file: "credentials.json"
  token_file: "token.json"

sync_settings:
  poll_interval_minutes: 15
  webhook_host: "0.0.0.0"
  webhook_port: 5000

mappings:
  - google_space_id: "spaces/AAAAA"
    discourse_category_id: 12
```

## Error Handling

### API Errors
- HTTP errors are caught and logged
- Retry logic for transient failures
- Graceful degradation

### Authentication
- OAuth token refresh for Google Chat
- API key validation for Discourse
- Clear error messages

### Data Integrity
- Database transactions for atomic operations
- Foreign key constraints
- Validation before sync

## Future Enhancements

### Real-time Google Chat Events
- Implement Google Cloud Pub/Sub subscription
- Receive instant notifications for new messages
- Eliminate polling delay

### Attachment Support
- Upload files from Google Chat to Discourse
- Sync Discourse uploads to Google Chat
- Handle file size limits

### Advanced Formatting
- Convert Google Chat formatting to Discourse
- Support embedded links and mentions
- Preserve code blocks and quotes

### Monitoring
- Add Prometheus metrics
- Health check endpoints
- Performance tracking

### Scalability
- Support multiple Discourse instances
- Handle rate limits gracefully
- Optimize database queries

## Testing Strategy

### Unit Tests
- Test each API client method
- Test sync logic in isolation
- Mock API responses

### Integration Tests
- Test full sync flow
- Verify mappings are created
- Check loop prevention

### Manual Testing
- Test with real APIs
- Verify content accuracy
- Check edge cases

## Security Considerations

### Credentials
- Never commit credentials to version control
- Use environment variables or secure storage
- Rotate keys periodically

### Webhooks
- Verify webhook signatures (Discourse supports this)
- Rate limit webhook endpoints
- Validate payload structure

### Data Privacy
- Respect user privacy settings
- Don't sync private spaces without permission
- Log only non-sensitive information

## Performance

### Optimization Strategies
- Batch API requests where possible
- Use pagination for large datasets
- Cache frequently accessed data
- Index database tables

### Resource Usage
- Minimal memory footprint
- Efficient database queries
- Asynchronous operations where beneficial

## Deployment

### Local Development
- Run directly with Python
- Use SQLite for database
- Configure for localhost

### Production
- Use systemd service
- Proper logging configuration
- Monitor resource usage
- Backup database regularly

### Docker (Future)
- Containerize application
- Use environment variables
- Volume for database
- Health checks
