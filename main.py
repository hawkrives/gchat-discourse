"""
Main service module that coordinates all synchronization components.
"""

import logging
import sys
import threading
import time
import schedule
from typing import Dict, Any

from config_loader import Config
from db import SyncDatabase
from google_chat_client import GoogleChatClient
from discourse_client import DiscourseClient
from sync_gchat_to_discourse import GChatToDiscourseSync
from sync_discourse_to_gchat import DiscourseToGChatSync
from webhook_listener import WebhookListener

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('sync_service.log')
    ]
)

logger = logging.getLogger(__name__)


class SyncService:
    """Main synchronization service coordinator."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the sync service.

        Args:
            config_path: Path to the configuration file
        """
        logger.info("Initializing sync service...")
        
        # Load configuration
        self.config = Config(config_path)
        
        # Initialize database
        self.db = SyncDatabase()
        
        # Initialize API clients
        self.gchat_client = GoogleChatClient(
            credentials_file=self.config.google_credentials_file,
            token_file=self.config.google_token_file
        )
        
        self.discourse_client = DiscourseClient(
            url=self.config.discourse_url,
            api_key=self.config.discourse_api_key,
            api_username=self.config.discourse_username
        )
        
        # Initialize sync handlers
        self.gchat_to_discourse = GChatToDiscourseSync(
            gchat_client=self.gchat_client,
            discourse_client=self.discourse_client,
            db=self.db
        )
        
        self.discourse_to_gchat = DiscourseToGChatSync(
            gchat_client=self.gchat_client,
            discourse_client=self.discourse_client,
            db=self.db,
            api_username=self.config.discourse_username
        )
        
        # Initialize webhook listener
        self.webhook_listener = WebhookListener(
            host=self.config.webhook_host,
            port=self.config.webhook_port
        )
        
        # Register webhook handlers
        self.webhook_listener.register_post_handler(self._handle_post_event)
        self.webhook_listener.register_topic_handler(self._handle_topic_event)
        
        logger.info("Sync service initialized successfully")

    def initial_sync(self):
        """Perform initial synchronization of configured spaces."""
        logger.info("Starting initial synchronization...")
        
        for mapping in self.config.space_mappings:
            space_id = mapping.get('google_space_id')
            category_id = mapping.get('discourse_category_id')
            parent_category_id = mapping.get('discourse_parent_category_id')
            
            if not space_id:
                logger.warning(f"Skipping mapping with no space_id: {mapping}")
                continue
            
            logger.info(f"Syncing space {space_id}...")
            
            # Sync space to category
            result_category_id = self.gchat_to_discourse.sync_space_to_category(
                space_id=space_id,
                category_id=category_id,
                parent_category_id=parent_category_id
            )
            
            if result_category_id:
                # Sync messages to posts
                synced_count = self.gchat_to_discourse.sync_messages_to_posts(space_id)
                logger.info(f"Synced {synced_count} messages from space {space_id}")
            else:
                logger.error(f"Failed to sync space {space_id}")
        
        logger.info("Initial synchronization complete")

    def periodic_sync(self):
        """Perform periodic catch-up synchronization."""
        logger.info("Running periodic catch-up sync...")
        
        for mapping in self.config.space_mappings:
            space_id = mapping.get('google_space_id')
            if not space_id:
                continue
            
            try:
                # Get last sync time
                last_sync = self.db.get_last_sync_time(space_id)
                
                # Sync messages since last sync
                synced_count = self.gchat_to_discourse.sync_messages_to_posts(
                    space_id=space_id,
                    since_timestamp=last_sync
                )
                
                logger.info(f"Periodic sync: {synced_count} new messages from {space_id}")
            except Exception as e:
                logger.error(f"Error in periodic sync for {space_id}: {e}", exc_info=True)
        
        logger.info("Periodic catch-up sync complete")

    def _handle_post_event(self, event_name: str, post_data: Dict[str, Any]):
        """Handle post events from Discourse webhook."""
        try:
            if event_name == 'created':
                self.discourse_to_gchat.sync_post_to_message(post_data)
            elif event_name == 'edited':
                self.discourse_to_gchat.sync_post_update(post_data)
            elif event_name == 'destroyed':
                logger.info(f"Post {post_data.get('id')} was destroyed")
                # Optionally handle deletions
        except Exception as e:
            logger.error(f"Error handling post event: {e}", exc_info=True)

    def _handle_topic_event(self, event_name: str, topic_data: Dict[str, Any]):
        """Handle topic events from Discourse webhook."""
        try:
            if event_name == 'created':
                self.discourse_to_gchat.handle_topic_creation(topic_data)
            elif event_name == 'edited':
                logger.info(f"Topic {topic_data.get('id')} was edited")
                # Optionally handle topic updates
            elif event_name == 'destroyed':
                logger.info(f"Topic {topic_data.get('id')} was destroyed")
                # Optionally handle deletions
        except Exception as e:
            logger.error(f"Error handling topic event: {e}", exc_info=True)

    def _run_scheduler(self):
        """Run the periodic sync scheduler in a separate thread."""
        logger.info("Starting scheduler thread...")
        
        # Schedule periodic sync
        schedule.every(self.config.poll_interval_minutes).minutes.do(self.periodic_sync)
        
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def run(self):
        """Start the sync service."""
        logger.info("Starting sync service...")
        
        try:
            # Run initial sync
            self.initial_sync()
            
            # Start scheduler in separate thread
            scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            scheduler_thread.start()
            
            # Start webhook listener (blocking)
            logger.info("Starting webhook listener...")
            self.webhook_listener.run()
            
        except KeyboardInterrupt:
            logger.info("Shutting down sync service...")
        except Exception as e:
            logger.error(f"Fatal error in sync service: {e}", exc_info=True)
        finally:
            self.db.close()
            logger.info("Sync service stopped")


def main():
    """Main entry point."""
    try:
        service = SyncService()
        service.run()
    except Exception as e:
        logger.error(f"Failed to start sync service: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
