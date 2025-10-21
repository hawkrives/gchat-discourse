# ABOUTME: Worker for processing failed export retries
# ABOUTME: Integrates with export pipeline to retry failed operations

import sqlite3
from typing import Callable, Dict
import structlog

from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()


class RetryWorker:
    """Process failed export retries."""

    def __init__(
        self,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        failed_export_manager: FailedExportManager,
        exporters: Dict[str, Callable],
    ):
        """
        Initialize retry worker.

        Args:
            state_conn: State database connection
            chat_conn: Chat database connection
            failed_export_manager: Failed export manager
            exporters: Dict mapping entity_type to export function
                      e.g., {'thread': thread_exporter.export_thread}
        """
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.failed_manager = failed_export_manager
        self.exporters = exporters

    def process_retries(self, max_retries: int = 100) -> Dict[str, int]:
        """
        Process ready retries.

        Args:
            max_retries: Maximum number of retries to process

        Returns:
            Dict with counts: {'success': N, 'failed': M, 'skipped': K}
        """
        retries = self.failed_manager.get_ready_retries(limit=max_retries)

        if not retries:
            logger.debug("no_retries_ready")
            return {"success": 0, "failed": 0, "skipped": 0}

        logger.info("processing_retries", count=len(retries))

        stats = {"success": 0, "failed": 0, "skipped": 0}

        for retry in retries:
            entity_type = retry["entity_type"]
            entity_id = retry["entity_id"]
            operation = retry["operation"]

            # Check if we have an exporter for this type
            exporter = self.exporters.get(entity_type)
            if not exporter:
                logger.error("no_exporter_for_type", entity_type=entity_type)
                stats["skipped"] += 1
                continue

            # Attempt export
            try:
                logger.info(
                    "retrying_export",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    attempt=retry["error_count"] + 1,
                )

                result = exporter(entity_id)

                if result:
                    # Success!
                    self.failed_manager.mark_success(entity_type, entity_id, operation)
                    stats["success"] += 1

                    logger.info("retry_succeeded", entity_type=entity_type, entity_id=entity_id)
                else:
                    # Export returned None/False
                    self.failed_manager.record_failure(
                        entity_type, entity_id, operation, "Export returned no result"
                    )
                    stats["failed"] += 1

            except Exception as e:
                # Export raised exception
                logger.error(
                    "retry_failed", entity_type=entity_type, entity_id=entity_id, error=str(e)
                )

                self.failed_manager.record_failure(entity_type, entity_id, operation, str(e))
                stats["failed"] += 1

        logger.info("retry_processing_complete", **stats)

        return stats
