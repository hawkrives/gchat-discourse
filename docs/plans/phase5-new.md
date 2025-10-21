# Phase 5 — Comprehensive Implementation Playbook

This is a prescriptive, step-by-step implementation plan for Phase 5 (Polish / Production Readiness) of gchat-mirror. It's written for a skilled engineer who starts with zero context about this codebase or domain. Follow it precisely. Keep changes small, test-driven, and frequent.

Principles (short):
- DRY: Don't repeat code or docs. Extract helpers.
- YAGNI: Only implement what the tests require.
- TDD: Write failing tests first. Make them small and deterministic.
- Frequent commits: Make small, focused commits with descriptive messages.

This playbook is prescriptive: each task lists exact files to create/edit, tests to add, and how to run them. If any step requires a design decision not covered here, stop and ask.

---

Table of contents
- Overview & goals
- Setup & conventions (how to run tests locally)
- Task list (ordered, bite-sized tasks)
  1. Write-queue helper (single-writer)
  2. Metrics endpoint on :4981
  3. Migration-check runner
  4. Integration test scaffolding
  5. macOS keychain guidance + helper docs
  6. Exception types and improved logging
  7. Documentation and checklists
- Testing strategy and examples
- Commit & PR guidance
- Appendix: exact file templates and snippets

---

Overview & goals

Goal: finish Phase 5 by making the system production-ready for a personal deployment: ensure correctness, add observability, and make maintenance safe.

Scope for this playbook: small, reversible, low-risk improvements. We'll implement a single-writer DB helper, a metrics endpoint, a migration-check runner, integration test scaffolds, macOS keychain docs, typed exceptions, and docs. We'll not redesign the app or add features beyond what's required.

Assumptions from the project owner (honor these):
- No CI. Developer will run tests locally on demand.
- Always retain attachments.
- macOS-first keychain for credentials.
- Metrics served at `:4981/metrics` and health server runs on :4981.
- Integration tests are manual and live under `tests/integration/`.

Setup & conventions (how to run tests locally)

Prereqs (developer machine):
- Python 3.11+
- `uv` CLI available (project uses `uv` to run pytest). If `uv` is not installed, use `python -m pytest`.

Commands you'll use repeatedly:

```bash
# Run unit tests (fast)
uv run pytest -k "not integration" -q

# Run all tests including integration (manual)
uv run pytest -q

# Run a single test file
uv run pytest tests/test_module.py -q

# Run a single test with verbose output
uv run pytest tests/test_module.py::test_name -vv
```

If `uv` is unavailable, use `python -m pytest` in its place.

Testing conventions
- Tests go under `tests/` (unit) and `tests/integration/` (integration).
- Unit tests must be fast (<100ms each ideally) and deterministic (no real network I/O). Use httpx mocking fixtures provided in the codebase.
- Integration tests are marked `@pytest.mark.integration` and use recorded fixtures; they are run manually by the developer.

Task list (ordered, bite-sized tasks)

Each task below follows the same pattern: small description, files to edit/create, exact code snippets or templates to use, tests to add, and how to run them.


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

```

Notes
- Keep this module minimal. It shouldn't depend on other project internals.

Tests to add
- Create `tests/test_write_queue.py` with the following tests:
  - test_enqueue_sql_runs: enqueue a simple CREATE TABLE + INSERT and verify via a read connection.
  - test_concurrent_enqueues: spawn 20 async tasks that enqueue inserts concurrently and assert final row_count == 20.

How to run
- Run unit tests:

```bash
uv run pytest tests/test_write_queue.py -q
```

Commit guidance
- Make small commits: add file, then add tests, then make fix to pass tests.

Task 2 — Metrics endpoint on :4981
---------------------------------

Why: Monitor basic system health and rates using Prometheus scraping.

Small contract
- Add `/metrics` route to existing health server on port 4981. Return Prometheus text exposition.

Files to edit/create
- `src/gchat_mirror/common/metrics.py` (new)
- Edit the health server file — `src/gchat_mirror/sync/health_server.py` or whichever file owns the health endpoint. If no health server exists, add `src/gchat_mirror/sync/health_server.py`.
- `tests/test_metrics.py` (new)

Implementation (metrics.py)

Create `src/gchat_mirror/common/metrics.py`:

```python
# ABOUTME: Metrics container and Prometheus exporter
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Metrics:
    spaces_synced: int = 0
    messages_synced: int = 0
    attachments_downloaded: int = 0

    def to_prometheus(self) -> str:
        lines = [
            "# TYPE gchat_mirror_spaces_synced gauge",
            f"gchat_mirror_spaces_synced {self.spaces_synced}",
            "# TYPE gchat_mirror_messages_synced gauge",
            f"gchat_mirror_messages_synced {self.messages_synced}",
            "# TYPE gchat_mirror_attachments_downloaded gauge",
            f"gchat_mirror_attachments_downloaded {self.attachments_downloaded}",
        ]
        return "\n".join(lines) + "\n"

metrics = Metrics()

```

Hook into health server
- Find the file that serves health checks: `src/gchat_mirror/sync/health_server.py` (search if necessary). Add a route `/metrics` that returns `metrics.to_prometheus()` with content-type `text/plain; version=0.0.4`.
- If no health server exists, create a simple Flask/Starlette/HTTPServer inside `src/gchat_mirror/sync/health_server.py` that serves `/health` and `/metrics`. Keep the dependency minimal: prefer stdlib `http.server` for no new deps.

Tests to add
- `tests/test_metrics.py`: import `src.gchat_mirror.common.metrics.metrics`, set values, call `.to_prometheus()` and assert strings present.

How to run

```bash
uv run pytest tests/test_metrics.py -q
```

Task 3 — Migration-check runner
--------------------------------

Why: Ensure migrations apply cleanly. Since there is no CI, provide a local script and optional pytest test.

Files to add
- `tools/check_migrations.py` (new script)
- `tests/test_migrations.py` (optional pytest wrapper)

Implementation
- `tools/check_migrations.py` should:
  1. Create a temporary sqlite file (tempdir)
  2. Import or read migration scripts from `migrations/` and execute them in numeric order against the DB
  3. On success, print final schema via `SELECT sql FROM sqlite_master WHERE type='table'` and exit 0

Make the script idempotent and safe; it must not alter repo files.

How to run

```bash
python tools/check_migrations.py
# or via pytest
uv run pytest tests/test_migrations.py -q
```

Task 4 — Integration tests scaffolding
-------------------------------------

Why: Integration tests are long and manual. Provide clear guidance and example test(s) that use recorded fixtures.

Files to add
- `tests/integration/README.md` (new)
- `tests/integration/test_full_workflow.py` (skeleton)

Contents of README.md (high level)
- How to run integration tests:
  - `uv run pytest tests/integration -m integration -q`
  - How to re-record fixtures (use httpx recorded fixtures tooling in repo)
- Where to put credentials for optional real runs (e.g., `client_secrets.json` in repo root)

Test skeleton
- Example test uses `httpx_mock` fixture from the codebase; load recorded fixture files; instantiate `SyncDaemon` with temp DB path, call start/stop, and assert DB contents. Keep it high-level and rely on repo's fixtures.

Task 5 — macOS keychain guidance + helper docs
--------------------------------------------

Why: Developers need clear instructions to set up OAuth credentials securely.

Files to add/edit
- `docs/plans/phase5-new.md` (this file — add a section) or `docs/user-guide.md` if preferred
- Optionally: `src/gchat_mirror/common/auth_keychain.py` (small helper) — implement only on request

Doc content (what to write)
- Step-by-step macOS Keychain usage using Python `keyring` package
- Example snippet to store and retrieve `discourse_api_key` and `google_tokens`
- Security notes: never commit `token.json` or API keys

Task 6 — Exception types and improved logging
--------------------------------------------

Files to add
- `src/gchat_mirror/common/exceptions.py` (new)
- Update a few code sites to raise typed exceptions (search for broad try/except blocks and improve one or two places only)
- `tests/test_exceptions.py` (new)

Implementation snippet for `exceptions.py`:

```python
# ABOUTME: Typed exceptions used across gchat-mirror
class GChatMirrorError(Exception):
    pass

class SyncError(GChatMirrorError):
    pass

class ExportError(GChatMirrorError):
    pass
```

Keep changes minimal: replace a generic `raise Exception(...)` inside sync or exporter with `raise SyncError(...)` in two places and add unit tests covering those paths.

Task 7 — Documentation and checklists
-----------------------------------

Files to edit/add
- `docs/plans/phase5-new.md` (this file — finalize)
- `docs/integration/README.md` (task 4)
- `docs/user-guide.md` (add sections: run tests, metrics, macOS keychain quickstart)

What to document precisely
- How to run unit tests and integration tests
- How to run the metrics/health server and verify `/metrics`
- How to run migration-check script
- How to use write-queue helper (short example)

Testing strategy and examples
----------------------------

Test design rules for this repo (for the engineer):
- Always write a failing test first. Keep tests small and focused.
- Mock external network calls using httpx/mock fixtures already present in the repo.
- Prefer in-memory or temporary DBs for unit tests. Use `tmp_path` pytest fixture.
- Mark long integration tests with `@pytest.mark.integration`.

Examples
- Unit test example for write_queue (outline):

```python
async def test_concurrent_enqueues(tmp_path):
    db = tmp_path / "test.db"
    q = AsyncWriteQueue(db)
    await q.start()

    async def worker(i):
        await q.enqueue_sql("INSERT INTO t (i) VALUES (?)", (i,))

    # schedule many workers
    await asyncio.gather(*(worker(i) for i in range(20)))
    await q.close()

    # assert rows present using run_sync_write
```

Commit & PR guidance
---------------------

- Make small commits: one commit per file added/changed when possible.
- Commit messages: `task: add write-queue helper` / `test: add write-queue tests (failing)` / `fix: make write-queue tests pass`.
- Run tests locally before committing.

Appendix: exact file templates and snippets
-----------------------------------------

- `src/gchat_mirror/common/write_queue.py`: see Task 1 for full file.
- `src/gchat_mirror/common/metrics.py`: see Task 2 for full file.
- `tools/check_migrations.py`: will be a small script that imports sqlite3 and runs files in `migrations/`.

Final notes and expectations
----------------------------

Follow the tasks in order. For each task:
1. Write tests first (they should fail).
2. Implement minimal code to satisfy tests.
3. Refactor if needed, keeping tests green.
4. Commit often and push to your branch.

If anything in the codebase prevents you from implementing a task (missing referenced file, unclear server structure), stop and flag the exact file and line where you're blocked. Don't guess large refactors.

When you're ready for me to begin implementing Task 1, say "start task 1".
