"""
Database module for storing mappings and preventing synchronization loops.
Uses SQLite to maintain state between Google Chat and Discourse.
"""

import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SyncDatabase:
    """Manages the SQLite database for sync state."""
    conn: sqlite3.Connection

    def __init__(self, db_path: str = "sync_db.sqlite"):
        """
        Initialize the database connection.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        """Create the database and tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = self.conn.cursor()

        # Table to map Google Chat spaces to Discourse categories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS space_to_category (
                google_space_id TEXT PRIMARY KEY,
                discourse_category_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table to map Google Chat threads to Discourse topics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_to_topic (
                google_thread_id TEXT PRIMARY KEY,
                discourse_topic_id INTEGER NOT NULL,
                google_space_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (google_space_id) REFERENCES space_to_category(google_space_id)
            )
        """)

        # Table to map Google Chat messages to Discourse posts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_to_post (
                google_message_id TEXT PRIMARY KEY,
                discourse_post_id INTEGER NOT NULL,
                google_thread_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (google_thread_id) REFERENCES thread_to_topic(google_thread_id)
            )
        """)

        # Table to store last sync timestamps for periodic catch-up
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                space_id TEXT PRIMARY KEY,
                last_sync_timestamp TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table to map Google Chat users to Discourse users
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_mapping (
                gchat_user_id TEXT PRIMARY KEY,
                gchat_display_name TEXT,
                gchat_email TEXT,
                discourse_username TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    # Space to Category mappings
    def add_space_category_mapping(self, google_space_id: str, discourse_category_id: int):
        """Add or update a space-to-category mapping."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO space_to_category (google_space_id, discourse_category_id)
            VALUES (?, ?)
        """, (google_space_id, discourse_category_id))
        self.conn.commit()
        logger.debug(f"Added mapping: {google_space_id} -> category {discourse_category_id}")

    def get_category_id(self, google_space_id: str) -> Optional[int]:
        """Get the Discourse category ID for a Google Chat space."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT discourse_category_id FROM space_to_category WHERE google_space_id = ?
        """, (google_space_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_space_id(self, discourse_category_id: int) -> Optional[str]:
        """Get the Google Chat space ID for a Discourse category."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT google_space_id FROM space_to_category WHERE discourse_category_id = ?
        """, (discourse_category_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # Thread to Topic mappings
    def add_thread_topic_mapping(self, google_thread_id: str, discourse_topic_id: int, google_space_id: str):
        """Add or update a thread-to-topic mapping."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO thread_to_topic (google_thread_id, discourse_topic_id, google_space_id)
            VALUES (?, ?, ?)
        """, (google_thread_id, discourse_topic_id, google_space_id))
        self.conn.commit()
        logger.debug(f"Added mapping: {google_thread_id} -> topic {discourse_topic_id}")

    def get_topic_id(self, google_thread_id: str) -> Optional[int]:
        """Get the Discourse topic ID for a Google Chat thread."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT discourse_topic_id FROM thread_to_topic WHERE google_thread_id = ?
        """, (google_thread_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_thread_id(self, discourse_topic_id: int) -> Optional[str]:
        """Get the Google Chat thread ID for a Discourse topic."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT google_thread_id FROM thread_to_topic WHERE discourse_topic_id = ?
        """, (discourse_topic_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # Message to Post mappings
    def add_message_post_mapping(self, google_message_id: str, discourse_post_id: int, google_thread_id: str):
        """Add or update a message-to-post mapping."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO message_to_post (google_message_id, discourse_post_id, google_thread_id)
            VALUES (?, ?, ?)
        """, (google_message_id, discourse_post_id, google_thread_id))
        self.conn.commit()
        logger.debug(f"Added mapping: {google_message_id} -> post {discourse_post_id}")

    def get_post_id(self, google_message_id: str) -> Optional[int]:
        """Get the Discourse post ID for a Google Chat message."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT discourse_post_id FROM message_to_post WHERE google_message_id = ?
        """, (google_message_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_message_id(self, discourse_post_id: int) -> Optional[str]:
        """Get the Google Chat message ID for a Discourse post."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT google_message_id FROM message_to_post WHERE discourse_post_id = ?
        """, (discourse_post_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # Sync state management
    def update_last_sync_time(self, space_id: str, timestamp: str):
        """Update the last sync timestamp for a space."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sync_state (space_id, last_sync_timestamp, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (space_id, timestamp))
        self.conn.commit()

    def get_last_sync_time(self, space_id: str) -> Optional[str]:
        """Get the last sync timestamp for a space."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT last_sync_timestamp FROM sync_state WHERE space_id = ?
        """, (space_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # User mappings
    def add_user_mapping(self, gchat_user_id: str, discourse_username: str,
                        gchat_display_name: Optional[str] = None,
                        gchat_email: Optional[str] = None):
        """Add or update a Google Chat user to Discourse user mapping."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_mapping 
            (gchat_user_id, discourse_username, gchat_display_name, gchat_email, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (gchat_user_id, discourse_username, gchat_display_name, gchat_email))
        self.conn.commit()
        logger.debug(f"Added user mapping: {gchat_user_id} -> {discourse_username}")

    def get_discourse_username(self, gchat_user_id: str) -> Optional[str]:
        """Get the Discourse username for a Google Chat user."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT discourse_username FROM user_mapping WHERE gchat_user_id = ?
        """, (gchat_user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_gchat_user_id(self, discourse_username: str) -> Optional[str]:
        """Get the Google Chat user ID for a Discourse username."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT gchat_user_id FROM user_mapping WHERE discourse_username = ?
        """, (discourse_username,))
        result = cursor.fetchone()
        return result[0] if result else None

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
