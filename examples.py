"""
Example usage demonstrations for the gchat-discourse sync service.
This file shows how to use various components programmatically.
"""

# Example 1: Using the Database module
def example_database():
    """Demonstrate database operations."""
    from db import SyncDatabase
    
    # Initialize database
    db = SyncDatabase("example.sqlite")
    
    # Add a space-to-category mapping
    db.add_space_category_mapping("spaces/AAAAA", 12)
    
    # Retrieve the category ID
    category_id = db.get_category_id("spaces/AAAAA")
    print(f"Category ID: {category_id}")
    
    # Add a thread-to-topic mapping
    db.add_thread_topic_mapping("spaces/AAAAA/threads/BBBBB", 42, "spaces/AAAAA")
    
    # Retrieve the topic ID
    topic_id = db.get_topic_id("spaces/AAAAA/threads/BBBBB")
    print(f"Topic ID: {topic_id}")
    
    # Clean up
    db.close()


# Example 2: Using the Configuration loader
def example_config():
    """Demonstrate configuration loading."""
    from config_loader import Config
    
    # Load configuration
    config = Config("config.yaml")
    
    # Access configuration values
    print(f"Discourse URL: {config.discourse_url}")
    print(f"Poll interval: {config.poll_interval_minutes} minutes")
    print(f"Webhook port: {config.webhook_port}")
    
    # Get space mappings
    for mapping in config.space_mappings:
        space_id = mapping.get('google_space_id')
        category_id = mapping.get('discourse_category_id')
        print(f"Mapping: {space_id} -> {category_id}")


# Example 3: Using the Google Chat client
def example_google_chat():
    """Demonstrate Google Chat API usage."""
    from google_chat_client import GoogleChatClient
    
    # Initialize client
    client = GoogleChatClient("credentials.json", "token.json")
    
    # List all spaces
    spaces = client.list_spaces()
    print(f"Found {len(spaces)} spaces")
    
    # Get space details
    if spaces:
        space_id = spaces[0]['name']
        space = client.get_space(space_id)
        print(f"Space name: {space['displayName']}")
        
        # List messages in the space
        response = client.list_messages(space_id, page_size=10)
        messages = response.get('messages', [])
        print(f"Recent messages: {len(messages)}")


# Example 4: Using the Discourse client
def example_discourse():
    """Demonstrate Discourse API usage."""
    from discourse_client import DiscourseClient
    
    # Initialize client
    client = DiscourseClient(
        url="http://localhost:8888",
        api_key="your_api_key",
        api_username="your_username"
    )
    
    # Get category details
    category = client.get_category(12)
    if category:
        print(f"Category: {category['category']['name']}")
    
    # List topics in category
    topics = client.list_topics_in_category(12)
    if topics:
        print(f"Topics in category: {len(topics.get('topic_list', {}).get('topics', []))}")


# Example 5: Manual sync operation
def example_manual_sync():
    """Demonstrate manual synchronization."""
    from google_chat_client import GoogleChatClient
    from discourse_client import DiscourseClient
    from db import SyncDatabase
    from sync_gchat_to_discourse import GChatToDiscourseSync
    
    # Initialize components
    gchat = GoogleChatClient("credentials.json", "token.json")
    discourse = DiscourseClient(
        url="http://localhost:8888",
        api_key="your_api_key",
        api_username="your_username"
    )
    db = SyncDatabase()
    
    # Create sync handler
    sync = GChatToDiscourseSync(gchat, discourse, db)
    
    # Sync a specific space
    space_id = "spaces/AAAAA"
    category_id = sync.sync_space_to_category(space_id, category_id=12)
    
    if category_id:
        # Sync messages
        count = sync.sync_messages_to_posts(space_id)
        print(f"Synced {count} messages")
    
    # Clean up
    db.close()


# Example 6: Webhook event handling
def example_webhook_handler():
    """Demonstrate webhook handling."""
    from google_chat_client import GoogleChatClient
    from discourse_client import DiscourseClient
    from db import SyncDatabase
    from sync_discourse_to_gchat import DiscourseToGChatSync
    
    # Initialize components
    gchat = GoogleChatClient("credentials.json", "token.json")
    discourse = DiscourseClient(
        url="http://localhost:8888",
        api_key="your_api_key",
        api_username="your_username"
    )
    db = SyncDatabase()
    
    # Create sync handler
    sync = DiscourseToGChatSync(gchat, discourse, db, "your_username")
    
    # Simulate a webhook event (normally comes from Discourse)
    post_data = {
        'id': 123,
        'topic_id': 45,
        'raw': 'Hello from Discourse!',
        'username': 'some_user'  # Not the API user
    }
    
    # Handle the event
    success = sync.sync_post_to_message(post_data)
    print(f"Sync {'successful' if success else 'failed'}")
    
    # Clean up
    db.close()


# Example 7: Complete service setup
def example_service():
    """Demonstrate full service setup."""
    from main import SyncService
    
    # This is what main.py does:
    service = SyncService("config.yaml")
    
    # Perform initial sync
    service.initial_sync()
    
    # Start the service (blocking)
    # service.run()  # Uncomment to actually run


if __name__ == "__main__":
    print("gchat-discourse Example Usage")
    print("=" * 60)
    print()
    print("This file contains example code snippets.")
    print("Uncomment and run individual examples to test.")
    print()
    print("Available examples:")
    print("  - example_database(): Database operations")
    print("  - example_config(): Configuration loading")
    print("  - example_google_chat(): Google Chat API")
    print("  - example_discourse(): Discourse API")
    print("  - example_manual_sync(): Manual sync operation")
    print("  - example_webhook_handler(): Webhook handling")
    print("  - example_service(): Full service setup")
    print()
    print("Note: Most examples require valid credentials.")
    print("=" * 60)
    
    # Uncomment to run an example:
    # example_database()
