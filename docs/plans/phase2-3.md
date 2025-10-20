# Phase 2 Part 3: Attachment Downloader

## Overview

Implement parallel attachment downloader with rate limiting, smart prioritization, and retry logic.

## Tasks

### 3.1 Parallel Attachment Downloader

**Test**: Downloads attachments with prioritization and rate limiting

**File**: `src/gchat_mirror/sync/attachment_downloader.py`

```python
# ABOUTME: Parallel attachment downloader with rate limiting and retry logic
# ABOUTME: Manages concurrent downloads with smart prioritization

import asyncio
import httpx
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List
import structlog
import multiprocessing

from gchat_mirror.sync.attachment_storage import AttachmentStorage

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
    
    def record_request(self):
        """Record that a request was made."""
        self.last_request_time = datetime.now()
    
    def set_retry_after(self, seconds: float):
        """Set a retry-after period."""
        self.retry_after_until = datetime.now() + timedelta(seconds=seconds)
        logger.warning("rate_limited", backoff_seconds=seconds)

class AttachmentDownloader:
    """Parallel attachment downloader."""
    
    def __init__(self, storage: AttachmentStorage, 
                 max_workers: Optional[int] = None):
        self.storage = storage
        self.max_workers = max_workers or max(1, multiprocessing.cpu_count() // 2)
        
        self.rate_limits: dict[str, RateLimitState] = {}
        self.rate_limit_lock = asyncio.Lock()
        
        self.stats = {
            'downloaded': 0,
            'failed': 0,
            'bytes_downloaded': 0,
        }
        
        logger.info("downloader_initialized", max_workers=self.max_workers)
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL for rate limiting."""
        from urllib.parse import urlparse
        return urlparse(url).netloc
    
    async def _wait_for_rate_limit(self, domain: str):
        """Wait if we're rate limited for this domain."""
        async with self.rate_limit_lock:
            if domain not in self.rate_limits:
                self.rate_limits[domain] = RateLimitState()
            
            wait_time = self.rate_limits[domain].should_wait()
            if wait_time:
                logger.debug("rate_limit_wait", domain=domain, seconds=wait_time)
                await asyncio.sleep(wait_time)
            
            self.rate_limits[domain].record_request()
    
    async def _download_file(self, session: httpx.AsyncClient,
                            task: DownloadTask) -> Optional[bytes]:
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
                logger.error("download_http_error",
                           status=response.status_code,
                           attachment=task.name)
                return None
            
            # Verify content length
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) != task.size_bytes:
                logger.warning("size_mismatch",
                             expected=task.size_bytes,
                             actual=content_length,
                             attachment=task.name)
            
            data = response.content
            
            if len(data) != task.size_bytes:
                logger.error("downloaded_size_mismatch",
                           expected=task.size_bytes,
                           actual=len(data),
                           attachment=task.name)
                return None
            
            logger.info("attachment_downloaded",
                       name=task.name,
                       size_mb=len(data) / 1024 / 1024)
            return data
        
        except asyncio.TimeoutError:
            logger.error("download_timeout", attachment=task.name)
            return None
        except httpx.HTTPError as e:
            logger.error("download_error", attachment=task.name, error=str(e))
            return None
    
    def _parse_retry_after(self, headers: dict) -> float:
        """Parse Retry-After header."""
        retry_after = headers.get('Retry-After', headers.get('retry-after'))
        
        if not retry_after:
            return 60.0
        
        try:
            return float(retry_after)
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime
                retry_time = parsedate_to_datetime(retry_after)
                wait_seconds = (retry_time - datetime.now()).total_seconds()
                return max(0, wait_seconds)
            except Exception:
                logger.warning("retry_after_parse_failed", value=retry_after)
                return 60.0
    
    async def _process_task(self, session: httpx.AsyncClient,
                           task: DownloadTask, semaphore: asyncio.Semaphore):
        """Process a single download task."""
        async with semaphore:
            try:
                data = await self._download_file(session, task)
                
                if data is None:
                    self.stats['failed'] += 1
                    return False
                
                # Store the attachment
                metadata = {
                    'name': task.name,
                    'content_type': task.content_type,
                    'source_url': task.source_url
                }
                
                self.storage.store_attachment(
                    task.attachment_id,
                    task.message_id,
                    metadata,
                    data
                )
                
                self.stats['downloaded'] += 1
                self.stats['bytes_downloaded'] += len(data)
                
                return True
            
            except Exception as e:
                logger.error("task_processing_error",
                           attachment=task.name,
                           error=str(e),
                           exc_info=True)
                self.stats['failed'] += 1
                return False
    
    async def _run_batch(self, tasks: List[DownloadTask]):
        """Run a batch of downloads."""
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async with httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=self.max_workers * 2,
                max_keepalive_connections=self.max_workers
            ),
            timeout=httpx.Timeout(300.0, connect=30.0),
            headers={'User-Agent': 'GChat-Mirror/1.0'},
            follow_redirects=True
        ) as session:
            tasks_coros = [
                self._process_task(session, task, semaphore)
                for task in tasks
            ]
            
            await asyncio.gather(*tasks_coros, return_exceptions=True)
    
    def download_pending(self, batch_size: int = 100):
        """Download pending attachments in batches."""
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
            asyncio.run(self._run_batch(tasks))
            
            logger.info("batch_complete",
                       downloaded=self.stats['downloaded'],
                       failed=self.stats['failed'],
                       mb=self.stats['bytes_downloaded'] / 1024 / 1024)
    
    def _get_pending_downloads(self, limit: int) -> List[dict]:
        """Get pending attachments from database."""
        cursor = self.storage.chat_conn.execute("""
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
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def _prioritize_tasks(self, pending: List[dict]) -> List[DownloadTask]:
        """Convert pending downloads to prioritized tasks."""
        tasks = []
        for row in pending:
            create_time = datetime.fromisoformat(row['create_time'].replace('Z', '+00:00'))
            
            task = DownloadTask(
                attachment_id=row['id'],
                message_id=row['message_id'],
                source_url=row['source_url'],
                name=row['name'],
                content_type=row['content_type'],
                size_bytes=row['size_bytes'],
                create_time=create_time,
                attempt=row['download_attempts']
            )
            tasks.append(task)
        
        return tasks
```

**Tests**:

```python
@pytest.mark.asyncio
async def test_attachment_downloader(tmp_path, httpx_mock):
    """Test parallel attachment downloading."""
    # Setup databases
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Create pending attachments
    for i in range(3):
        chat_db.conn.execute("""
            INSERT INTO messages (id, create_time)
            VALUES (?, ?)
        """, (f'msg{i}', '2025-01-15T10:00:00Z'))
        
        chat_db.conn.execute("""
            INSERT INTO attachments 
            (id, message_id, name, size_bytes, source_url, downloaded)
            VALUES (?, ?, ?, ?, ?, FALSE)
        """, (f'att{i}', f'msg{i}', f'file{i}.txt', 100,
              f'https://example.com/file{i}'))
    chat_db.conn.commit()
    
    # Mock downloads
    for i in range(3):
        httpx_mock.add_response(
            url=f'https://example.com/file{i}',
            content=b'X' * 100
        )
    
    # Download
    downloader = AttachmentDownloader(storage, max_workers=2)
    downloader.download_pending(batch_size=10)
    
    # Verify all downloaded
    cursor = chat_db.conn.execute("""
        SELECT COUNT(*) FROM attachments WHERE downloaded = TRUE
    """)
    assert cursor.fetchone()[0] == 3
    
    # Verify stats
    assert downloader.stats['downloaded'] == 3
    assert downloader.stats['failed'] == 0
    assert downloader.stats['bytes_downloaded'] == 300

@pytest.mark.asyncio
async def test_rate_limit_handling(tmp_path, httpx_mock):
    """Test handling of 429 rate limit responses."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Create pending attachment
    chat_db.conn.execute("""
        INSERT INTO messages (id, create_time)
        VALUES ('msg1', '2025-01-15T10:00:00Z')
    """)
    chat_db.conn.execute("""
        INSERT INTO attachments 
        (id, message_id, name, size_bytes, source_url, downloaded)
        VALUES ('att1', 'msg1', 'file.txt', 100, 'https://example.com/file', FALSE)
    """)
    chat_db.conn.commit()
    
    # Mock rate limit response
    httpx_mock.add_response(
        url='https://example.com/file',
        status_code=429,
        headers={'Retry-After': '5'}
    )
    
    downloader = AttachmentDownloader(storage, max_workers=1)
    downloader.download_pending(batch_size=10)
    
    # Should have failed (not downloaded)
    assert downloader.stats['failed'] == 1
    assert downloader.stats['downloaded'] == 0
    
    # Check rate limit was recorded
    domain = 'example.com'
    assert domain in downloader.rate_limits
    assert downloader.rate_limits[domain].retry_after_until is not None

@pytest.mark.asyncio  
async def test_download_prioritization(tmp_path, httpx_mock):
    """Test that recent messages with small files get priority."""
    chat_db = setup_test_chat_db(tmp_path)
    att_db = setup_test_attachments_db(tmp_path)
    storage = AttachmentStorage(att_db.conn, chat_db.conn)
    
    # Create attachments with different dates and sizes
    test_data = [
        ('att1', 'msg1', '2025-01-10T10:00:00Z', 1000000),  # Old, large
        ('att2', 'msg2', '2025-01-15T10:00:00Z', 100),      # Recent, small (should be first)
        ('att3', 'msg3', '2025-01-15T10:00:00Z', 500000),   # Recent, medium (should be second)
    ]
    
    for att_id, msg_id, create_time, size in test_data:
        chat_db.conn.execute("""
            INSERT INTO messages (id, create_time)
            VALUES (?, ?)
        """, (msg_id, create_time))
        
        chat_db.conn.execute("""
            INSERT INTO attachments 
            (id, message_id, name, size_bytes, source_url, downloaded)
            VALUES (?, ?, ?, ?, ?, FALSE)
        """, (att_id, msg_id, f'{att_id}.bin', size, f'https://example.com/{att_id}'))
    
    chat_db.conn.commit()
    
    downloader = AttachmentDownloader(storage, max_workers=1)
    
    # Get prioritized tasks
    pending = downloader._get_pending_downloads(10)
    tasks = downloader._prioritize_tasks(pending)
    
    # Verify order: recent and small first
    assert tasks[0].attachment_id == 'att2'  # Recent, smallest
    assert tasks[1].attachment_id == 'att3'  # Recent, medium
    assert tasks[2].attachment_id == 'att1'  # Old, large
```

## Completion Criteria

- [ ] AttachmentDownloader class implemented
- [ ] Parallel downloads work with CPU/2 workers
- [ ] Rate limiting per domain works
- [ ] Retry-After header parsing works (numeric and HTTP-date)
- [ ] Smart prioritization (recent first, then smallest)
- [ ] Failed downloads tracked with exponential backoff
- [ ] All async tests pass
