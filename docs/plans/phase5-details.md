## Phase 5 — Detailed Implementation Plan

This document breaks Phase 5 (Polish / Production Readiness) into concrete, small, testable tasks tailored to this repository and the constraints for personal-use deployment (no CI, macOS-first keychain, metrics via HTTP, always retain attachments, integration tests run manually).

Each task includes a short "contract" (inputs/outputs, success criteria), edge cases, implementation notes, and tests to add.

---

### High-level goals

- Achieve comprehensive test coverage (unit + well-scoped integration tests)
- Improve database reliability and performance (single-writer helper, WAL, indexes)
- Add lightweight observability (metrics endpoint at :4981/metrics + health server)
- Improve error handling and monitoring hooks
- Document procedures: running integration tests, macOS keychain setup, migration checks

---

### Work items (small, actionable)

1) Write-queue helper (single-writer)
------------------------------------

Contract
- Input: async tasks needing to perform DB writes (callables or SQL + params)
- Output: writes applied to SQLite via a single connection; returns results or raises errors
- Success: All unit tests pass; stress test shows no concurrent writer errors under simulated concurrency

Edge cases
- Long-running write tasks blocking queue (apply timeout / cancellation)
- Writer crashes (ensure queue drains or restarts)
- Transaction support (batched unit-of-work)

Implementation notes
- File: `src/gchat_mirror/common/write_queue.py`
- Provide an AsyncWriteQueue class exposing `enqueue(callable, *args, **kwargs)` and `enqueue_sql(sql, params)` helpers
- Internally run a background asyncio Task that opens a single sqlite3 connection with WAL enabled and serially executes items
- Provide a synchronous wrapper for code paths that are synchronous (so tests can call directly)
- Ensure proper shutdown: `close()` awaits queue drain and stops background task

Tests to add
- Unit test: multiple coroutines enqueueing writes in parallel and verify DB content consistent
- Unit test: exception in a write is propagated to the caller
- Unit test: transaction/batch API commits atomically

Milestones
- Add class and initial tests (fast)
- Integrate into one small module via dependency injection to validate runtime behavior

Notes
- Keep API minimal to avoid large refactors in other modules. Provide a backward-compatible helper `run_in_write_queue(sync_fn)` for existing sync code to call.

2) Metrics HTTP endpoint (Prometheus text exposition)
-------------------------------------------------

Contract
- Input: metrics updated by app components
- Output: HTTP endpoint available at `:4981/metrics` returning Prometheus-format text
- Success: Endpoint returns metrics lines; unit test verifies metrics response includes expected metric names

Edge cases
- Large metric payloads
- Metrics serialization errors

Implementation notes
- Reuse existing health server on port 4981; add a `/metrics` route
- File: `src/gchat_mirror/common/metrics.py` (dataclass and `to_prometheus()` method)
- Implementation: if health server uses a small WSGI/ASGI framework, add route there. Otherwise add a small HTTP handler using `http.server` or `uvicorn` for ASGI. Keep it opt-in via config but enabled by default per your choice.

Tests to add
- Unit test: metrics.to_prometheus() returns valid lines for sample metrics
- Small integration test: spin up the health server in test and GET /metrics, assert 200 and content-type text/plain

Milestones
- Add metrics dataclass and unit tests
- Hook endpoint into existing health server

3) Migration-check helper (apply migrations to temp DB)
--------------------------------------------------

Contract
- Input: repository migration scripts in `migrations/`
- Output: script/test that applies each migration sequentially to a temporary DB and ensures no exceptions
- Success: Running test passes locally (no CI) and prints final schema information

Edge cases
- Migrations that depend on external state

Implementation notes
- Add `tests/test_migrations.py` or a small script `tools/check_migrations.py`
- Use `tempfile.TemporaryDirectory()` and fresh SQLite DB files; run each migration file in order.
- Make the runner idempotent and produce a debug SQL export on success

Tests to add
- Direct test: run migration-check as a pytest test (mark as slow if desired)

Milestones
- Add migration runner and simple test

4) Integration tests structure and guidance
-----------------------------------------

Contract
- Input: recorded fixtures and local dev environment
- Output: `tests/integration/` folder with examples and instructions for manual runs
- Success: Developer can run integration tests manually and they use recorded fixtures by default

Edge cases
- Tests that try to call real network accidentally

Implementation notes
- Create `tests/integration/README.md` describing how to run integration tests, where to place credentials for optional real runs, and how to regenerate fixtures
- Ensure recorded fixtures live in `tests/fixtures/` and httpx mocking is used by default

Tests to add
- Example long-running test with marker @pytest.mark.integration in `tests/integration/test_full_workflow.py` that uses httpx recorded fixtures

Milestones
- Add README and skeleton integration test

5) macOS keychain auth documentation + helper
-------------------------------------------

Contract
- Input: user has OAuth client_secrets.json
- Output: step-by-step instructions for storing/reading credentials from macOS Keychain, plus a small helper function to read secrets
- Success: developer can follow docs and authenticate locally; helper returns stored credentials

Edge cases
- Missing keychain entries

Implementation notes
- Add doc fragment to `docs/plans/phase5-details.md` and link into user-guide
- Recommend using `keyring` Python package (macOS backend) and show sample code using it

Milestones
- Add docs and a small helper snippet in `src/gchat_mirror/common/auth_keychain.py` (optional — implement only if you ask)

6) Error handling improvements
------------------------------

Contract
- Input: existing exception paths
- Output: small module additions of typed exception classes and improved logging for key failure paths
- Success: unit tests cover raising and handling of new exception types

Edge cases
- Deep call stacks where wrapping loses context

Implementation notes
- Add `src/gchat_mirror/common/exceptions.py` with `GChatMirrorError`, `SyncError`, `ExportError`
- Replace/augment a handful of places that catch generic exceptions to log structured context

Milestones
- Add module and two tests validating correct exception types and logging

7) Docs and checklists
----------------------

Contract
- Input: this plan and repo conventions
- Output: `docs/plans/phase5-details.md` (this file) plus a short `docs/integration/README.md` and updates to `docs/user-guide.md` describing running the health/metrics server on :4981 and macOS keychain setup
- Success: docs are present and explain how to run integration tests, how to enable metrics, and how to use the write-queue helper

Milestones
- Add integration README and user-guide snippets

---

### Test strategy and locations

- Unit tests: `tests/` (fast, run frequently)
- Integration tests: `tests/integration/` (manual runs; marked with `@pytest.mark.integration`)
- Migration-check: `tests/test_migrations.py` (fast, but optional run)

### Health & Metrics binding

- Health server continues to run on port 4981. Add `/metrics` path so both health and metrics are served on the same port.
- Metrics format: Prometheus text exposition (plain text, content-type `text/plain; version=0.0.4`)

### Minimal change policy

- Keep changes small and reversible. For each new module, add unit tests first.
- Provide backward-compatible wrappers so existing code doesn't have to be refactored all at once.

---

If you approve this plan, I will implement item (1) `write_queue.py` and its unit tests first, then proceed in the order above. If you prefer a different order, tell me which items to prioritize.

Implementation owner: me (I will open small, focused edits on request)

Constraints honored: no CI changes, macOS-first keychain docs, retain attachments, metrics via HTTP on :4981, integration tests kept separate for manual runs.
