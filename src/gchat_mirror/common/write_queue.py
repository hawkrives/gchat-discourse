# ABOUTME: Single-writer helper for sqlite3. Provides AsyncWriteQueue and simple sync wrapper.
# ABOUTME: Minimal async-friendly writer queue to serialize SQLite writes.
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional


class WriteQueueClosed(Exception):
    pass


class AsyncWriteQueue:
    """Simple async queue that executes callables on a single sqlite3 connection.

    Usage:
    q = AsyncWriteQueue(db_path)
    await q.start()
    await q.enqueue_sql("INSERT ...", params)
    await q.close()
    """

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._closing = False

    async def start(self):
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._writer())

    async def enqueue_sql(self, sql: str, params: tuple = ()):  # pragma: no cover - trivial
        fut = asyncio.get_running_loop().create_future()
        await self._queue.put((sql, params, fut))
        return await fut

    async def enqueue(self, fn: Callable[[sqlite3.Connection], Any]):
        fut = asyncio.get_running_loop().create_future()
        await self._queue.put((fn, None, fut))
        return await fut

    async def _writer(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass

        while True:
            item = await self._queue.get()
            if item is None:
                break
            payload, params, fut = item
            try:
                if callable(payload):
                    result = payload(conn)
                    fut.set_result(result)
                else:
                    cursor = conn.execute(payload, params or ())
                    fut.set_result(cursor)
            except Exception as e:
                fut.set_exception(e)
            finally:
                self._queue.task_done()

        conn.close()

    async def close(self):
        if self._task is None:
            return
        # signal writer to exit
        await self._queue.put(None)
        await self._task
        self._task = None


def run_sync_write(db_path: Path, fn: Callable[[sqlite3.Connection], Any]):
    """Convenience for synchronous code. Opens a short-lived connection and runs fn."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    try:
        return fn(conn)
    finally:
        conn.commit()
        conn.close()
