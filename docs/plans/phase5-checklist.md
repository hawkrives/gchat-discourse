# Phase 5 — Completion Checklist

This checklist collects the small, verifiable items required to consider Phase 5 (Polish) complete for a personal deployment.

Core items
- [ ] Comprehensive unit test coverage (target: repository tests green locally)
- [ ] Integration test scaffolding and instructions in `tests/integration`
- [x] Migration-check script (`tools/check_migrations.py`) present
- [x] Metrics endpoint available (`/metrics`) and documented
- [x] macOS keychain guidance and `auth_keychain` helper
- [x] Exception types added (`src/gchat_mirror/common/exceptions.py`)

Developer tasks (small, ordered)
1. Run unit tests locally and fix failures
2. Run `tools/check_migrations.py` and inspect schema output
3. Start the sync daemon and verify `http://localhost:4981/health` and `/metrics`
4. Verify documentation in `docs/user-guide.md`

Notes
- Task 1 from the original playbook (write-queue helper) has been removed from the Phase 5 checklist by design and should not be reintroduced without explicit approval.
