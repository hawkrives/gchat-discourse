import asyncio
import sqlite3

import pytest

from gchat_mirror.common.write_queue import AsyncWriteQueue, run_sync_write


@pytest.mark.asyncio
async def test_enqueue_sql_runs(tmp_path):
    db = tmp_path / "test.db"
    # create table via run_sync_write
    def create_table(conn: sqlite3.Connection):
        conn.execute("CREATE TABLE t (i INTEGER)")

    run_sync_write(db, create_table)

    q = AsyncWriteQueue(db)
    await q.start()

    await q.enqueue_sql("INSERT INTO t (i) VALUES (?)", (1,))
    await q.close()

    # verify
    conn = sqlite3.connect(str(db))
    cur = conn.execute("SELECT count(*) FROM t")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_enqueues(tmp_path):
    db = tmp_path / "test2.db"

    def create_table(conn: sqlite3.Connection):
        conn.execute("CREATE TABLE t (i INTEGER)")

    run_sync_write(db, create_table)

    q = AsyncWriteQueue(db)
    await q.start()

    async def worker(i):
        await q.enqueue_sql("INSERT INTO t (i) VALUES (?)", (i,))

    await asyncio.gather(*(worker(i) for i in range(20)))
    await q.close()

    conn = sqlite3.connect(str(db))
    cur = conn.execute("SELECT count(*) FROM t")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 20
