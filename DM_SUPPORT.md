# Google Chat DM to Discourse Chat DM Support

## Overview

This document describes the implementation of Google Chat Direct Message (DM) synchronization to Discourse Chat DMs.

## Features Implemented

### 1. Automatic Space Type Detection
The service now automatically detects whether a Google Chat space is a room or a direct message:
- **Room spaces**: Synced to Discourse categories and topics (existing behavior)
- **DM spaces**: Synced to Discourse chat channels (new behavior)

### 2. User Management
Each Google Chat user is automatically mapped to a Discourse user:
- Users are created in Discourse when first encountered in a DM
- Username format: `gchat_<displayname>` (e.g., `gchat_john_doe`)
- Email format: `<username>@gchat-sync.local` (fake email for sync users)
- Usernames are made unique by appending numbers if conflicts occur

### 3. DM Synchronization
Google Chat DM messages are synchronized to Discourse chat messages:
- DM spaces are mapped to Discourse chat channels
- Messages are attributed to the appropriate users
- Current implementation uses text attribution (e.g., `**@gchat_john_doe**: message`)

## Database Schema Changes

### New Tables

#### `user_mapping`
Tracks Google Chat users to Discourse users:
```sql
CREATE TABLE user_mapping (
    google_user_id TEXT PRIMARY KEY,
    google_user_name TEXT NOT NULL,
    google_user_email TEXT,
    discourse_username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `dm_space_to_chat_channel`
Maps Google Chat DM spaces to Discourse chat channels:
```sql
CREATE TABLE dm_space_to_chat_channel (
    google_space_id TEXT PRIMARY KEY,
    discourse_chat_channel_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `dm_message_to_chat_message`
Maps individual DM messages:
```sql
CREATE TABLE dm_message_to_chat_message (
    google_message_id TEXT PRIMARY KEY,
    discourse_chat_message_id INTEGER NOT NULL,
    google_space_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (google_space_id) REFERENCES dm_space_to_chat_channel(google_space_id)
);
```

## API Methods Added

### GoogleChatClient
- `is_dm_space(space)`: Checks if a space is a DM
- `get_space_members(space_id)`: Retrieves all members of a space
- `get_user_info(user_name)`: Placeholder for user info retrieval

### DiscourseClient
- `create_user(name, email, username, password, active)`: Creates a new user
- `user_exists(username)`: Checks if a user exists
- `create_chat_channel(name, usernames, description)`: Creates a chat channel
- `get_chat_channel(channel_id)`: Retrieves chat channel details
- `create_chat_message(channel_id, message, in_reply_to_id)`: Creates a chat message
- `update_chat_message(channel_id, message_id, new_message)`: Updates a chat message

### SyncDatabase
- `add_user_mapping()`, `get_discourse_username()`, `get_google_user_id()`
- `add_dm_channel_mapping()`, `get_chat_channel_id()`, `get_dm_space_id()`
- `add_dm_message_mapping()`, `get_chat_message_id()`, `get_dm_message_id()`

### GChatToDiscourseSync
- `_ensure_user_exists(sender)`: Creates/retrieves Discourse user for a Google Chat user
- `sync_dm_space_to_chat_channel(space_id)`: Syncs a DM space to a chat channel
- `sync_dm_messages_to_chat(space_id, since_timestamp)`: Syncs DM messages
- `_sync_dm_message_to_chat(message, space_id, channel_id)`: Syncs individual DM message

## Configuration

No special configuration is needed for DM spaces. Simply add the DM space ID to your `config.yaml`:

```yaml
mappings:
  - google_space_id: "spaces/AAAAA"  # Regular room space
    discourse_category_id: 12
  - google_space_id: "spaces/BBBBB"  # DM space - automatically detected
```

## Requirements

- Discourse instance with the **Discourse Chat plugin** installed and enabled
- **Admin API Key**: The Discourse API key must have admin privileges to enable posting as different users
- Google Chat API access with appropriate scopes
- All existing prerequisites from README.md

## Known Limitations

1. **User Information**: Google Chat API doesn't provide a direct user lookup endpoint. User information is extracted from message sender data.

2. **Bot Users**: Bot users are skipped during user creation as they typically shouldn't have Discourse accounts.

## Implementation Details

### User Impersonation

Messages are posted as the actual Google Chat users using Discourse's API user impersonation feature. When an admin API key is used with the `Api-Username` header, Discourse allows posting content as any user. This provides proper attribution without requiring individual API keys for each user.

The sync service:
1. Creates a Discourse user for each Google Chat participant (if not already exists)
2. Uses the admin API key with the `Api-Username` header set to the target user
3. Posts messages, topics, and chat messages as that user

## Future Enhancements

1. **User Profile Sync**: Sync user avatars and profile information from Google Chat to Discourse

3. **Bidirectional DM Sync**: Implement Discourse Chat → Google Chat DM synchronization

4. **User Permissions**: Map Google Chat user permissions to Discourse user groups

5. **Rich Formatting**: Preserve message formatting when syncing between platforms

## Testing

To test DM synchronization:

1. Find a Google Chat DM space ID using the Google Chat API
2. Add it to your `config.yaml` mappings
3. Run the sync service
4. Verify that:
   - A Discourse chat channel is created
   - Discourse users are created for all DM participants
   - Messages are synced with proper attribution

## Troubleshooting

**Issue**: Users not being created
- Check Discourse permissions for the API user
- Verify the Discourse Chat plugin is installed and enabled
- Check logs for error messages

**Issue**: Messages not syncing
- Verify the chat channel was created successfully
- Check database mappings with `sqlite3 sync_db.sqlite`
- Review logs for sync errors

**Issue**: Duplicate usernames
- The service automatically appends numbers to avoid conflicts
- Check the `user_mapping` table to see resolved usernames
