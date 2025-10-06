# Quick Start Guide

This guide will help you get the Google Chat ↔️ Discourse sync service running in under 10 minutes.

## Prerequisites Checklist

- [ ] Python 3.10+ installed
- [ ] Local Discourse instance running
- [ ] Google Cloud account
- [ ] Terminal/command line access

## Step 1: Clone and Setup (2 minutes)

```bash
# Clone the repository
git clone https://github.com/hawkrives/gchat-discourse.git
cd gchat-discourse

# Run interactive setup
./run.sh setup
```

This creates `config.yaml` from the template.

## Step 2: Google Chat API Setup (3 minutes)

1. **Go to Google Cloud Console**: https://console.cloud.google.com/

2. **Create/Select Project**:
   - Click "Select a project" → "New Project"
   - Name it (e.g., "gchat-discourse-sync")
   - Click "Create"

3. **Enable Google Chat API**:
   - Search for "Google Chat API" in the search bar
   - Click "Enable"

4. **Create OAuth Credentials**:
   - Navigate to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Desktop app"
   - Name: "Discourse Sync"
   - Click "Create"

5. **Download Credentials**:
   - Click the download icon next to your OAuth client
   - Save as `credentials.json` in the project directory

## Step 3: Discourse API Setup (2 minutes)

1. **Generate API Key**:
   - Go to your Discourse admin panel
   - Navigate to `/admin/api/keys`
   - Click "New API Key"
   - Description: "Google Chat Sync"
   - User Level: "All Users"
   - Click "Save"

2. **Copy Credentials**:
   - Copy the API Key
   - Note your username

## Step 4: Configuration (2 minutes)

Edit `config.yaml`:

```yaml
discourse:
  url: "http://localhost:8888"  # Your Discourse URL
  api_key: "paste_your_api_key_here"
  api_username: "your_username"

google:
  credentials_file: "credentials.json"
  token_file: "token.json"

sync_settings:
  poll_interval_minutes: 15
  webhook_host: "0.0.0.0"
  webhook_port: 5000

mappings:
  - google_space_id: "spaces/AAAAAAAAAAA"  # See below for finding this
    discourse_category_id: 12  # See below for finding this
```

### Finding Google Chat Space IDs

**Option 1: From URL**
- Open Google Chat in browser
- Navigate to the space
- Look at URL: `https://mail.google.com/chat/u/0/#chat/space/AAAAAAAAAAA`
- Space ID is: `spaces/AAAAAAAAAAA`

**Option 2: List Spaces (requires OAuth first)**
```python
from google_chat_client import GoogleChatClient
client = GoogleChatClient("credentials.json", "token.json")
spaces = client.list_spaces()
for space in spaces:
    print(f"{space['displayName']}: {space['name']}")
```

### Finding Discourse Category IDs

**Option 1: From URL**
- Go to the category in Discourse
- Look at URL: `http://localhost:8888/c/category-name/12`
- Category ID is: `12`

**Option 2: From API**
```bash
curl -H "Api-Key: YOUR_API_KEY" \
     -H "Api-Username: your_username" \
     http://localhost:8888/categories.json
```

## Step 5: Install Dependencies (1 minute)

```bash
./run.sh install
```

Or manually:
```bash
pip install -r requirements.txt
```

## Step 6: Setup Discourse Webhook (2 minutes)

1. **Create Webhook**:
   - Go to Discourse admin: `/admin/api/webhooks`
   - Click "New Webhook"

2. **Configure**:
   - Payload URL: `http://YOUR_SERVER_IP:5000/discourse-webhook`
   - Content Type: `application/json`
   - Secret: (leave empty for now)
   - Select events: ✓ Post Event, ✓ Topic Event
   - Active: ✓ Check
   - Click "Save"

**For local testing**: Use ngrok to expose localhost
```bash
ngrok http 5000
# Use the ngrok URL in webhook configuration
```

## Step 7: Validate Setup (1 minute)

```bash
./run.sh validate
```

You should see:
```
✓ All Python files have valid syntax
✓ All modules imported successfully
✓ Validation PASSED
```

## Step 8: First Run! (Now!)

```bash
./run.sh run
```

Or:
```bash
python main.py
```

### What Happens on First Run

1. **OAuth Flow**: Browser opens for Google authentication
   - Click "Allow"
   - Token saved to `token.json`

2. **Initial Sync**:
   - Fetches Google Chat spaces
   - Creates Discourse categories
   - Syncs existing messages
   - Sets up mappings

3. **Service Starts**:
   - Webhook listener on port 5000
   - Periodic sync every 15 minutes
   - Ready for real-time updates!

### Checking Logs

**Console output**: Real-time logs
```
INFO - Sync service initialized successfully
INFO - Starting initial synchronization...
INFO - Synced 42 messages from space spaces/AAAAA
INFO - Starting webhook listener on 0.0.0.0:5000
```

**Log file**: `sync_service.log`
```bash
tail -f sync_service.log
```

## Troubleshooting

### "No module named 'google'"
```bash
pip install -r requirements.txt
```

### "Configuration file not found"
```bash
./run.sh setup
# Then edit config.yaml
```

### "Invalid OAuth credentials"
- Re-download `credentials.json` from Google Cloud Console
- Delete `token.json` and re-run

### "Discourse API error"
- Check API key has "All Users" scope
- Verify Discourse URL is correct
- Test with: `curl http://localhost:8888`

### Webhook not receiving events
- Check firewall settings
- For local: Use ngrok
- Verify webhook is active in Discourse admin

## Testing the Sync

### Test Google Chat → Discourse

1. Send a message in mapped Google Chat space
2. Wait ~15 minutes for periodic sync (or restart service)
3. Check Discourse category for new topic/post

### Test Discourse → Google Chat

1. Create a post in mapped Discourse category
2. Should appear in Google Chat immediately
3. Check webhook logs for confirmation

## Next Steps

- **Monitor**: Check logs regularly
- **Tune**: Adjust `poll_interval_minutes` in config
- **Scale**: Add more space mappings
- **Customize**: Modify sync logic for your needs

## Getting Help

- Check logs: `tail -f sync_service.log`
- Review issues: https://github.com/hawkrives/gchat-discourse/issues
- Check ARCHITECTURE.md for technical details
- Read README.md for comprehensive guide

## Summary

You now have:
- ✅ Bidirectional sync between Google Chat and Discourse
- ✅ Real-time updates from Discourse webhooks
- ✅ Periodic catch-up for Google Chat messages
- ✅ State management to prevent loops
- ✅ Logging for monitoring

**Enjoy your synced conversations!** 🎉
