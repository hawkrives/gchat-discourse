# Google Chat ↔️ Discourse Bidirectional Sync

A service that provides real-time, two-way synchronization between Google Chat spaces and Discourse forum categories. Messages, threads, and topics are automatically synced in both directions, allowing teams to use their preferred platform while maintaining a unified conversation.

## Features

- **Two-way synchronization**: Chat messages sync to Discourse posts, and vice versa
- **Real-time updates**: Discourse webhooks for instant synchronization
- **Periodic catch-up**: Scheduled syncs to handle offline periods
- **State management**: SQLite database prevents duplicate syncing and infinite loops
- **Thread/Topic mapping**: Google Chat threads map to Discourse topics
- **Space/Category mapping**: Google Chat spaces map to Discourse categories
- **DM support**: Google Chat direct messages map to Discourse chat channels
- **User management**: Automatic creation of Discourse users for Google Chat participants

## Architecture

### Components

1. **Google Chat API Client** (`google_chat_client.py`): Handles OAuth authentication and API interactions with Google Chat
2. **Discourse API Client** (`discourse_client.py`): Manages Discourse REST API calls
3. **Database** (`db.py`): SQLite database for mapping and state management
4. **Sync Modules**:
   - `sync_gchat_to_discourse.py`: Google Chat → Discourse synchronization
   - `sync_discourse_to_gchat.py`: Discourse → Google Chat synchronization
5. **Webhook Listener** (`webhook_listener.py`): Flask server for receiving Discourse events
6. **Main Service** (`main.py`): Orchestrates all components

### Data Flow

```
Google Chat Room Space ←→ Discourse Category
    Thread            ←→ Topic
    Message           ←→ Post

Google Chat DM Space ←→ Discourse Chat Channel
    Message          ←→ Chat Message

Google Chat User ←→ Discourse User
```

**Note**: The service automatically detects whether a Google Chat space is a room or a direct message and syncs it to the appropriate Discourse structure (category/topic or chat channel).

## Prerequisites

- Python 3.10 or higher
- A local or accessible Discourse instance
- **Discourse Chat plugin** installed and enabled (required for DM synchronization)
- Google Cloud Platform account with Chat API enabled
- Network access for webhooks (if running locally, use ngrok or similar)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/hawkrives/gchat-discourse.git
cd gchat-discourse
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### 1. Set up Google Chat API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Google Chat API**
4. Navigate to "APIs & Services" → "Credentials"
5. Create an **OAuth 2.0 Client ID** for a "Desktop app"
6. Download the credentials and save as `credentials.json` in the project directory

### 2. Set up Discourse API

1. Navigate to your Discourse admin panel: `/admin/api/keys`
2. Generate a new **All-Access API Key**
3. Note your API key and username

### 3. Configure the Service

1. Copy the example configuration:
```bash
cp config.yaml.example config.yaml
```

2. Edit `config.yaml` with your settings:

```yaml
discourse:
  url: "http://localhost:8888"  # Your Discourse URL
  api_key: "YOUR_DISCOURSE_API_KEY"
  api_username: "your_discourse_username"

google:
  credentials_file: "credentials.json"
  token_file: "token.json"

sync_settings:
  poll_interval_minutes: 15
  webhook_host: "0.0.0.0"
  webhook_port: 5000

mappings:
  - google_space_id: "spaces/AAAAAAAAAAA"  # Replace with actual space ID
    discourse_category_id: 12
  - google_space_id: "spaces/BBBBBBBBBBB"
    discourse_parent_category_id: 12
```

**Finding Google Chat Space IDs:**
- Use the Google Chat API Explorer or list spaces programmatically
- Space IDs are in the format `spaces/AAAAAAAAAAA`
- The service will automatically detect if a space is a DM or room and sync accordingly

**DM Space Syncing:**
- Google Chat DM spaces are automatically synced to Discourse chat channels
- Users participating in DMs are automatically created in Discourse with usernames in the format `gchat_<displayname>`
- No special configuration is needed for DM spaces - just add the space ID to the mappings

### 4. Set up Discourse Webhooks

1. In Discourse admin panel, go to "API" → "Webhooks"
2. Create a new webhook with:
   - **Payload URL**: `http://YOUR_SERVER_IP:5000/discourse-webhook`
   - **Content Type**: `application/json`
   - **Events**: Select "Post Event" and "Topic Event"
   - **Active**: Check to enable

**Note**: If running locally, use a tunneling service like ngrok:
```bash
ngrok http 5000
# Use the ngrok URL in Discourse webhook configuration
```

## Usage

### First Run

On the first run, you'll be prompted to authorize the application with Google:

1. Run the service:
```bash
python main.py
```

2. A browser window will open for Google OAuth authentication
3. Grant the requested permissions
4. The token will be saved to `token.json` for future use

### Running the Service

Simply run:
```bash
python main.py
```

The service will:
1. Perform an initial sync of configured spaces
2. Start the webhook listener for real-time Discourse updates
3. Run periodic catch-up syncs based on the configured interval

### Logs

- Console output: Real-time logs to stdout
- Log file: `sync_service.log` in the project directory

## Database Schema

The service maintains state in `sync_db.sqlite`:

- **space_to_category**: Maps Google Chat spaces to Discourse categories
- **thread_to_topic**: Maps Google Chat threads to Discourse topics
- **message_to_post**: Maps Google Chat messages to Discourse posts
- **sync_state**: Tracks last sync timestamps for each space

## Loop Prevention

The service prevents infinite loops by:

1. Checking if posts are created by the API user (ignoring them)
2. Checking database mappings to see if content originated from the other platform
3. Storing bidirectional mappings for all synced content

## Limitations

- **Real-time Google Chat events**: Requires Google Cloud Pub/Sub setup (advanced feature)
- **Edit detection**: Both platforms support edit webhooks/events
- **Deletions**: Not automatically synced (can be added in handlers)
- **Attachments**: Not currently supported
- **Formatting**: Some formatting may be lost in translation between platforms

## Development

### Project Structure

```
gchat-discourse/
├── main.py                      # Main service entry point
├── config_loader.py             # Configuration management
├── db.py                        # Database operations
├── google_chat_client.py        # Google Chat API client
├── discourse_client.py          # Discourse API client
├── sync_gchat_to_discourse.py   # GChat → Discourse sync
├── sync_discourse_to_gchat.py   # Discourse → GChat sync
├── webhook_listener.py          # Flask webhook server
├── requirements.txt             # Python dependencies
├── config.yaml.example          # Example configuration
└── README.md                    # This file
```

### Adding Features

To add new features:

1. **Custom message formatting**: Modify the sync modules to transform content
2. **Attachment support**: Extend API clients to handle file uploads
3. **Advanced filtering**: Add logic in sync modules to filter messages
4. **Pub/Sub integration**: Implement real-time Google Chat events (see Phase 4 notes)

## Troubleshooting

### Authentication Issues

- **Google**: Delete `token.json` and re-authenticate
- **Discourse**: Verify API key has "All Users" scope

### Webhook Not Receiving Events

- Check firewall/port forwarding settings
- Verify webhook URL is accessible from Discourse server
- Check Discourse webhook logs in admin panel

### Messages Not Syncing

- Check logs for error messages
- Verify mappings in `config.yaml` are correct
- Check database for existing mappings: `sqlite3 sync_db.sqlite`

### Database Issues

- To reset: `rm sync_db.sqlite` (will re-sync all messages)
- To inspect: `sqlite3 sync_db.sqlite` then use SQL queries

## License

This project is licensed under the GPL-3.0 License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review logs for error details
