# ABOUTME: Parallel attachment downloader with rate limiting and retry logic
# ABOUTME: Manages concurrent downloads with smart prioritization

from __future__ import annotations

import asyncio
import multiprocessing
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import httpx  # type: ignore
import structlog  # type: ignore

from gchat_mirror.sync.attachment_storage import AttachmentStorage
from gchat_mirror.common.metrics import metrics as metrics_module

if TYPE_CHECKING:
    from gchat_mirror.sync.daemon import SyncDaemon

logger = structlog.get_logger()


@dataclass
class DownloadTask:
    attachment_id: str
    message_id: str
    source_url: str
    name: str
    content_type: str
    size_bytes: int
    create_time: datetime
    attempt: int = 0


@dataclass
class RateLimitState:
    """Track rate limiting per domain."""

    retry_after_until: Optional[datetime] = None
    last_request_time: Optional[datetime] = None
    min_request_interval: float = 0.1

    def should_wait(self) -> Optional[float]:
        """Returns seconds to wait, or None if OK to proceed."""
        now = datetime.now()

        if self.retry_after_until and now < self.retry_after_until:
            return (self.retry_after_until - now).total_seconds()

        if self.last_request_time:
            elapsed = (now - self.last_request_time).total_seconds()
            if elapsed < self.min_request_interval:
                return self.min_request_interval - elapsed

        return None

    def record_request(self) -> None:
        """Record that a request was made."""
        self.last_request_time = datetime.now()

    def set_retry_after(self, seconds: float) -> None:
        """Set a retry-after period."""
        self.retry_after_until = datetime.now() + timedelta(seconds=seconds)
        logger.warning("rate_limited", backoff_seconds=seconds)


class AttachmentDownloader:
    """Parallel attachment downloader."""

    def __init__(self, storage: AttachmentStorage, max_workers: Optional[int] = None, daemon: Optional["SyncDaemon"] = None):
        self.storage = storage
        self.max_workers = max_workers or max(1, multiprocessing.cpu_count() // 2)
        # Optional SyncDaemon reference used to update global counters
        self.daemon = daemon

        self.rate_limits: dict[str, RateLimitState] = {}
        self.rate_limit_lock = asyncio.Lock()

        self.stats = {
            "downloaded": 0,
            "failed": 0,
            "bytes_downloaded": 0,
        }

        logger.info("downloader_initialized", max_workers=self.max_workers)

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL for rate limiting."""
        return urlparse(url).netloc

    async def _wait_for_rate_limit(self, domain: str) -> None:
        """Wait if we're rate limited for this domain."""
        async with self.rate_limit_lock:
            if domain not in self.rate_limits:
                self.rate_limits[domain] = RateLimitState()

            wait_time = self.rate_limits[domain].should_wait()
            if wait_time:
                logger.debug("rate_limit_wait", domain=domain, seconds=wait_time)
                await asyncio.sleep(wait_time)

            self.rate_limits[domain].record_request()

    async def _download_file(
        self, session: httpx.AsyncClient, task: DownloadTask
    ) -> Optional[bytes]:
        """Download a single file with retry and rate limit handling."""
        domain = self._get_domain(task.source_url)

        await self._wait_for_rate_limit(domain)

        try:
            timeout = httpx.Timeout(300.0, connect=30.0)
            response = await session.get(task.source_url, timeout=timeout)

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = self._parse_retry_after(response.headers)

                async with self.rate_limit_lock:
                    self.rate_limits[domain].set_retry_after(retry_after)

                return None

            # Handle errors
            if response.status_code >= 400:
                logger.error(
                    "download_http_error", status=response.status_code, attachment=task.name
                )
                return None

            # Verify content length
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) != task.size_bytes:
                logger.warning(
                    "size_mismatch",
                    expected=task.size_bytes,
                    actual=content_length,
                    attachment=task.name,
                )

            data = response.content

            if len(data) != task.size_bytes:
                logger.error(
                    "downloaded_size_mismatch",
                    expected=task.size_bytes,
                    actual=len(data),
                    attachment=task.name,
                )
                return None

            logger.info("attachment_downloaded", name=task.name, size_mb=len(data) / 1024 / 1024)
            return data

        except asyncio.TimeoutError:
            logger.error("download_timeout", attachment=task.name)
            return None
        except httpx.HTTPError as e:
            logger.error("download_error", attachment=task.name, error=str(e))
            return None

    def _parse_retry_after(self, headers: httpx.Headers) -> float:
        """Parse Retry-After header."""
        retry_after = headers.get("Retry-After", headers.get("retry-after"))

        if not retry_after:
            return 60.0

        try:
            return float(retry_after)
        except ValueError:
            try:
                retry_time = parsedate_to_datetime(retry_after)
                wait_seconds = (retry_time - datetime.now()).total_seconds()
                return max(0, wait_seconds)
            except Exception:
                logger.warning("retry_after_parse_failed", value=retry_after)
                return 60.0

    async def _process_task(
        self, session: httpx.AsyncClient, task: DownloadTask, semaphore: asyncio.Semaphore
    ) -> bool:
        """Process a single download task."""
        async with semaphore:
            try:
                data = await self._download_file(session, task)

                if data is None:
                    # Mark download as failed in database
                    self.storage.chat_conn.execute(
                        """
                        UPDATE attachments
                        SET download_attempts = download_attempts + 1,
                            download_error = 'Download failed'
                        WHERE id = ?
                    """,
                        (task.attachment_id,),
                    )
                    self.storage.chat_conn.commit()

                    self.stats["failed"] += 1
                    return False

                # Store the attachment data
                import hashlib

                sha256 = hashlib.sha256(data).hexdigest()
                size = len(data)

                # Determine storage type
                from gchat_mirror.sync.attachment_storage import INLINE_THRESHOLD, CHUNK_SIZE

                storage_type = "inline" if size < INLINE_THRESHOLD else "chunked"

                # Store in attachments.db
                if storage_type == "inline":
                    self.storage.attachments_conn.execute(
                        """
                        INSERT INTO attachment_inline (attachment_id, data)
                        VALUES (?, ?)
                    """,
                        (task.attachment_id, data),
                    )
                else:
                    # Store in chunks
                    total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
                    for i in range(total_chunks):
                        start = i * CHUNK_SIZE
                        end = min(start + CHUNK_SIZE, size)
                        chunk_data = data[start:end]
                        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

                        self.storage.attachments_conn.execute(
                            """
                            INSERT INTO attachment_chunks
                            (attachment_id, chunk_index, data, size_bytes, sha256_hash)
                            VALUES (?, ?, ?, ?, ?)
                        """,
                            (task.attachment_id, i, chunk_data, len(chunk_data), chunk_hash),
                        )

                # Update metadata in chat.db
                self.storage.chat_conn.execute(
                    """
                    UPDATE attachments
                    SET downloaded = TRUE,
                        download_time = CURRENT_TIMESTAMP,
                        sha256_hash = ?,
                        storage_type = ?,
                        chunk_size = ?,
                        total_chunks = ?
                    WHERE id = ?
                """,
                    (
                        sha256,
                        storage_type,
                        CHUNK_SIZE if storage_type == "chunked" else None,
                        (size + CHUNK_SIZE - 1) // CHUNK_SIZE
                        if storage_type == "chunked"
                        else None,
                        task.attachment_id,
                    ),
                )

                self.storage.chat_conn.commit()
                self.storage.attachments_conn.commit()

                self.stats["downloaded"] += 1
                self.stats["bytes_downloaded"] += len(data)

                # Update central metrics container
                try:
                    metrics_module.attachments_downloaded += 1
                except Exception:
                    # defensive; ensure attribute exists
                    metrics_module.attachments_downloaded = getattr(metrics_module, "attachments_downloaded", 0) + 1

                # Update daemon counter if provided
                try:
                    if self.daemon is not None and hasattr(self.daemon, "increment_attachments_downloaded"):
                        # best-effort, don't fail the download on counter errors
                        self.daemon.increment_attachments_downloaded(1)
                except Exception:
                    logger.debug("daemon_counter_update_failed")

                logger.info("attachment_stored", attachment_id=task.attachment_id, size=size)

                return True

            except Exception as e:
                # Mark download as failed in database
                self.storage.chat_conn.execute(
                    """
                    UPDATE attachments
                    SET download_attempts = download_attempts + 1,
                        download_error = ?
                    WHERE id = ?
                """,
                    (str(e), task.attachment_id),
                )
                self.storage.chat_conn.commit()

                logger.error(
                    "task_processing_error",
                    attachment=task.name,
                    error=str(e),
                    exc_info=True,
                )
                self.stats["failed"] += 1
                return False

    async def _run_batch(self, tasks: list[DownloadTask]) -> None:
        """Run a batch of downloads."""
        semaphore = asyncio.Semaphore(self.max_workers)

        async with httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=self.max_workers * 2,
                max_keepalive_connections=self.max_workers,
            ),
            timeout=httpx.Timeout(300.0, connect=30.0),
            headers={"User-Agent": "GChat-Mirror/1.0"},
            follow_redirects=True,
        ) as session:
            tasks_coros = [self._process_task(session, task, semaphore) for task in tasks]

            await asyncio.gather(*tasks_coros, return_exceptions=True)

    async def download_pending_async(self, batch_size: int = 100) -> None:
        """Download pending attachments in batches (async version)."""
        while True:
            # Get pending downloads
            pending = self._get_pending_downloads(batch_size)

            if not pending:
                logger.info("no_pending_downloads")
                break

            logger.info("processing_batch", count=len(pending))

            # Sort: recent first, then smallest within recent
            tasks = self._prioritize_tasks(pending)

            # Run the batch
            await self._run_batch(tasks)

            logger.info(
                "batch_complete",
                downloaded=self.stats["downloaded"],
                failed=self.stats["failed"],
                mb=self.stats["bytes_downloaded"] / 1024 / 1024,
            )

    def download_pending(self, batch_size: int = 100) -> None:
        """Download pending attachments in batches (sync wrapper)."""
        asyncio.run(self.download_pending_async(batch_size))

    def _get_pending_downloads(self, limit: int) -> list[dict[str, Any]]:
        """Get pending attachments from database."""
        cursor = self.storage.chat_conn.execute(
            """
            SELECT a.id, a.message_id, a.source_url, a.name,
                   a.content_type, a.size_bytes, a.download_attempts,
                   m.create_time
            FROM attachments a
            JOIN messages m ON a.message_id = m.id
            WHERE a.downloaded = FALSE
              AND a.download_attempts < 5
              AND (
                  a.download_attempts = 0
                  OR datetime(a.created_at,
                      '+' || (a.download_attempts * a.download_attempts * 5) || ' minutes')
                      < datetime('now')
              )
            ORDER BY
                m.create_time DESC,
                a.size_bytes ASC
            LIMIT ?
        """,
            (limit,),
        )

        return [dict(row) for row in cursor.fetchall()]

    def _prioritize_tasks(self, pending: list[dict[str, Any]]) -> list[DownloadTask]:
        """Convert pending downloads to prioritized tasks."""
        tasks = []
        for row in pending:
            create_time = datetime.fromisoformat(row["create_time"].replace("Z", "+00:00"))

            task = DownloadTask(
                attachment_id=row["id"],
                message_id=row["message_id"],
                source_url=row["source_url"],
                name=row["name"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                create_time=create_time,
                attempt=row["download_attempts"],
            )
            tasks.append(task)

        return tasks
