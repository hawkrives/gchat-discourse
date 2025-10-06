# User Impersonation and DM Support Guide

This guide explains how to use the new user impersonation and direct message features in gchat-discourse.

## Features Overview

### 1. User Impersonation

All messages synced from Google Chat are now posted in Discourse as the actual sender, not as the API user. This provides:

- **Proper Attribution**: Messages show the correct author in Discourse
- **User Context**: User profiles, avatars, and metadata are preserved
- **Natural Conversations**: Discussions look natural with proper authorship

#### How It Works

1. When a Google Chat message is received, the service extracts sender information
2. If the sender doesn't exist in Discourse, a new user is automatically created
3. Messages are posted using Discourse's API impersonation (via `Api-Username` header)
4. The mapping is stored in the database for future messages

#### Username Generation

Google Chat display names are sanitized to create valid Discourse usernames:

- Special characters are removed
- Spaces are replaced with underscores
- Names are limited to 20 characters
- Minimum length of 3 characters is enforced

Example mappings:
- "John Doe" → "john_doe"
- "Alice Smith" → "alice_smith"
- "User@123!" → "user123"

### 2. Direct Message Support

Google Chat direct messages (DMs) are synced to Discourse Chat DM channels.

#### Requirements

- Discourse instance with the Chat plugin enabled
- Admin API key with full permissions

#### How It Works

1. The service detects when a Google Chat space is a DM (vs a room)
2. Participants are identified from messages in the DM
3. A Discourse Chat DM channel is created with the same participants
4. Messages are synced as chat messages (not forum posts)
5. All messages maintain proper author attribution via impersonation

#### DM vs Room Sync

| Google Chat Type | Discourse Destination | Content Type |
|-----------------|----------------------|--------------|
| Room/Space | Forum Category | Topics & Posts |
| Direct Message | Chat DM Channel | Chat Messages |

## Configuration

No additional configuration is required! The service automatically:

- Detects DM spaces
- Creates users as needed
- Uses impersonation for all messages
- Routes content to the appropriate destination

### API Key Requirements

Your Discourse API key must have **admin** permissions to:
- Create users
- Impersonate users (post as other users)
- Access Chat API endpoints

To create an admin API key:
1. Go to your Discourse admin panel: `/admin/api/keys`
2. Create a new key with "All Users" scope
3. Set the key as "Master Key" or ensure it has admin privileges

## Database Schema

The service uses these tables for user and DM management:

### user_mapping

Maps Google Chat users to Discourse usernames:

| Column | Type | Description |
|--------|------|-------------|
| gchat_user_id | TEXT | Google Chat user ID (e.g., 'users/123456') |
| gchat_display_name | TEXT | Display name from Google Chat |
| gchat_email | TEXT | Email address (if available) |
| discourse_username | TEXT | Generated Discourse username |
| created_at | TIMESTAMP | When mapping was created |
| updated_at | TIMESTAMP | Last update time |

### dm_space_to_chat_channel

Maps Google Chat DM spaces to Discourse Chat channels:

| Column | Type | Description |
|--------|------|-------------|
| google_space_id | TEXT | Google Chat DM space ID |
| discourse_chat_channel_id | INTEGER | Discourse Chat channel ID |
| created_at | TIMESTAMP | When mapping was created |

## Troubleshooting

### Users Not Being Created

**Symptoms**: Messages show as the API user instead of the actual sender

**Solutions**:
1. Check that your API key has admin permissions
2. Verify email configuration in Discourse allows user creation
3. Check logs for user creation errors

### DMs Not Syncing

**Symptoms**: Google Chat DMs don't appear in Discourse

**Solutions**:
1. Verify Discourse Chat plugin is enabled
2. Check that the API user has access to create Chat channels
3. Look for errors in `sync_service.log`
4. Verify the Google Chat space is actually a DM (not a room)

### Username Conflicts

**Symptoms**: User creation fails due to existing username

**Solutions**:
- The service automatically handles this by fetching the existing user
- If issues persist, check for username collisions in Discourse

## Loop Prevention

The service prevents infinite sync loops by:

1. **Primary Method**: Checking if a post/message has a mapping in the database
   - If a message originated from Google Chat, it won't be synced back
   - If a post originated from Discourse, it won't be synced to Chat

2. **Backwards Compatibility**: Also checks if content was created by the default API user
   - Existing setups continue to work without changes

This approach works correctly with user impersonation because:
- All synced content is tracked in the database regardless of who posted it
- The impersonation happens at the API level, but mappings are still stored
- Loop prevention is based on origin tracking, not username checking

## Examples

### Example 1: Google Chat Room → Discourse Category

1. User "Alice" sends "Hello!" in Google Chat room "Team Chat"
2. Service detects message from Alice
3. Service creates Discourse user "alice" if needed
4. Topic/Post created in mapped category as user "alice"
5. Post shows "alice" as author in Discourse

### Example 2: Google Chat DM → Discourse Chat DM

1. User "Bob" sends "Hi there" in Google Chat DM with "Alice"
2. Service detects this is a DM space
3. Service creates Discourse users "bob" and "alice" if needed
4. Service creates Chat DM channel between "bob" and "alice"
5. Message sent as "bob" in the Chat DM
6. Message shows "bob" as sender in Discourse Chat

### Example 3: Discourse → Google Chat (with impersonation)

1. User "alice" posts in Discourse topic (linked to Google Chat thread)
2. Service checks: did this post originate from Google Chat?
   - If yes: ignore (already synced)
   - If no: sync to Google Chat
3. Message created in Google Chat thread
4. Note: Google Chat doesn't support impersonation, so message appears from the OAuth user

## Testing

You can test the new features by:

1. **Test User Creation**:
   - Send a message from a new Google Chat user
   - Check Discourse admin panel for the new user
   - Verify username sanitization worked correctly

2. **Test Impersonation**:
   - Send messages from different Google Chat users
   - Check Discourse to confirm each message shows correct author
   - Verify no messages show the API username

3. **Test DM Sync**:
   - Create a new Google Chat DM
   - Send messages in the DM
   - Check Discourse Chat for the DM channel
   - Verify messages appear with correct senders

## Migration from Previous Versions

If you were using an older version without impersonation:

1. **Existing Messages**: Will continue to show the API user as author
2. **New Messages**: Will use impersonation and show correct authors
3. **Database**: New tables are created automatically on first run
4. **No Action Required**: The service handles migration transparently

## API Reference

### UserManager

```python
from gchat_discourse.user_manager import UserManager

# Create user manager
user_manager = UserManager(discourse_client, db)

# Get or create a Discourse user for a Google Chat sender
sender = {
    'name': 'users/123456',
    'displayName': 'John Doe',
    'email': 'john@example.com'
}
username = user_manager.get_or_create_discourse_user(sender)
```

### Discourse Chat API

```python
from gchat_discourse.discourse_client import DiscourseClient

# Create Discourse client
discourse = DiscourseClient(url, api_key, api_username)

# Create a DM channel
result = discourse.create_chat_dm_channel(['user1', 'user2'])
channel_id = result['channel']['id']

# Send a message with impersonation
discourse.send_chat_message(
    channel_id=channel_id,
    message="Hello!",
    impersonate_username='user1'
)
```

## Further Reading

- [Discourse API Documentation](https://docs.discourse.org/)
- [Discourse Chat Plugin](https://github.com/discourse/discourse-chat)
- [Google Chat API Reference](https://developers.google.com/chat/api)
