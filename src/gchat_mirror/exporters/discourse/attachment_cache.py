# ABOUTME: Attachment upload and URL caching for Discourse
# ABOUTME: Ensures attachments are uploaded once and reused

import sqlite3
from typing import Dict, Optional
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.sync.attachment_storage import AttachmentStorage

logger = structlog.get_logger()

class AttachmentCache:
    """Cache for uploaded attachment URLs."""
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 attachment_storage: AttachmentStorage):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.storage = attachment_storage
        self._memory_cache: Dict[str, str] = {}
    
    def get_or_upload_attachment(self, attachment_id: str) -> Optional[str]:
        """
        Get Discourse URL for attachment, uploading if needed.
        
        Args:
            attachment_id: Google Chat attachment ID
        
        Returns:
            Discourse URL, or None if upload fails
        """
        # Check memory cache first
        if attachment_id in self._memory_cache:
            return self._memory_cache[attachment_id]
        
        # Check database cache
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'attachment' AND source_id = ?
        """, (attachment_id,))
        
        result = cursor.fetchone()
        if result:
            url = result[0]  # discourse_id stores the URL
            self._memory_cache[attachment_id] = url
            logger.debug("attachment_cache_hit", attachment_id=attachment_id)
            return url
        
        # Need to upload
        return self._upload_attachment(attachment_id)
    
    def _upload_attachment(self, attachment_id: str) -> Optional[str]:
        """Upload attachment to Discourse."""
        # Get attachment metadata from chat database
        cursor = self.chat_conn.execute("""
            SELECT name, content_type, size_bytes
            FROM attachments
            WHERE id = ?
        """, (attachment_id,))
        
        metadata_row = cursor.fetchone()
        if not metadata_row:
            logger.error("attachment_metadata_not_found",
                        attachment_id=attachment_id)
            return None
        
        filename, mime_type, size = metadata_row
        
        # Get file data from attachment storage
        try:
            file_data = self.storage.retrieve_attachment(attachment_id)
        except (ValueError, Exception) as e:
            logger.error("attachment_data_not_found",
                        attachment_id=attachment_id,
                        error=str(e))
            return None
        
        try:
            # Upload to Discourse
            logger.info("uploading_attachment",
                       attachment_id=attachment_id,
                       filename=filename,
                       size=len(file_data))
            
            upload_result = self.discourse.upload_file(
                filename=filename or 'attachment',
                file_data=file_data,
                content_type=mime_type or 'application/octet-stream'
            )
            
            # Get URL from result
            url = upload_result.get('url') or upload_result.get('short_url')
            
            if not url:
                logger.error("no_url_in_upload_result",
                            attachment_id=attachment_id,
                            result=upload_result)
                return None
            
            # Cache the URL
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('attachment', ?, 'attachment', ?)
            """, (attachment_id, url))
            self.state_conn.commit()
            
            self._memory_cache[attachment_id] = url
            
            logger.info("attachment_uploaded",
                       attachment_id=attachment_id,
                       url=url)
            
            return url
        
        except Exception as e:
            logger.error("attachment_upload_failed",
                        attachment_id=attachment_id,
                        error=str(e))
            return None
    
    def preload_cache(self, attachment_ids: list):
        """
        Preload attachment URLs into memory cache.
        
        Useful for batch processing to avoid repeated database queries.
        """
        if not attachment_ids:
            return
        
        placeholders = ','.join('?' * len(attachment_ids))
        cursor = self.state_conn.execute(f"""
            SELECT source_id, discourse_id FROM export_mappings
            WHERE source_type = 'attachment'
            AND source_id IN ({placeholders})
        """, attachment_ids)
        
        for source_id, discourse_id in cursor.fetchall():
            self._memory_cache[source_id] = discourse_id
        
        logger.debug("attachment_cache_preloaded",
                    count=len(self._memory_cache))
