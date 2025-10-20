# Phase 1 Progress Notes

## Completed Work
- Repository structure aligned with the gchat-mirror reference layout (src/gchat_mirror, migrations, tests, docs).
- Core sync subsystems implemented: migrations, database wrapper, auth credentials handling, Google Chat client, storage layer, and sync daemon orchestration.
- CLI entry point added with global debug/data-dir/config-dir options plus sync start/status/backfill placeholders, export-discourse placeholders, and client management placeholders.
- Structured logging configured through structlog with JSON output, shared `get_logger`, and reused across modules.
- Configuration loader built on `tomllib`, merging defaults with file data and environment overrides; defaults exposed through `get_default_sync_config`.
- Integration test exercises full sync loop against mocked Chat API, verifying spaces, users, and messages persisted into SQLite.
- README documents requirements, configuration steps, CLI usage, and development workflow.

## Key Decisions
- Adopted Ruff’s formatter (`ruff format`) instead of Black to consolidate lint/format tooling.
- Declined to implement migration downgrades; migrations are upgrade-only with tests reflecting that stance.
- Environment overrides follow `GCHAT_MIRROR_` prefix with nested keys split on underscores, supporting two-level maps (`SECTION_KEY`) while preserving defaults via deep merge.
- Sync daemon ensures migrations run on startup and performs integrity checks before contacting the API.

## Outstanding Items
- Future phases will replace CLI placeholders with real exporters and client management flows.
- Monitoring/health endpoints and backfill mechanics remain scheduled for later phases.
