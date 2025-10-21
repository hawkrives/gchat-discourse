# Fix plan — align DB schema & code to tests (no backward compatibility)

Date: 2025-10-20

Summary
- The test run shows a cluster of failures caused by the runtime database schema not matching the assumptions in exporter and sync code. Key mismatches:
  - `messages` table missing `deleted` column
  - `attachments` table uses `content_type` while exporter/tests expect `mime_type`
  - `threads` table is absent
  - `message_revisions` schema differs (tests expect `revision_id` and `update_time`; migrations currently create `revision_number` and `last_update_time`)

Decision (per instruction):
- We will not attempt backward compatibility. The migrations and code will be made to match the schema shape the tests and exporters expect.

High-level approach
1. Add a single migration that brings `chat.db` to the expected shape for the exporter and sync code:
   - Create `threads` table.
   - Add `deleted INTEGER DEFAULT 0` column to `messages`.
   - Replace / re-create `message_revisions` with the schema the exporter expects (fields: `message_id`, `revision_id`, `text`, `update_time`).
   - Replace / re-create `attachments` table fields to expose `mime_type` (or add `mime_type` and drop/ignore `content_type`).

2. Update application code to use the final schema names directly (no fallbacks):
   - `src/gchat_mirror/exporters/discourse/message_exporter.py`
     - SELECTs should include `deleted` and revisions should query `revision_id`/`update_time`.
     - Attachments SELECT should request `mime_type`.
   - `src/gchat_mirror/exporters/discourse/attachment_cache.py`
     - Read `mime_type` column when uploading and cache-ing attachment metadata.
   - `src/gchat_mirror/sync/storage.py`
     - Persist attachments and revisions using the new column names (write `mime_type`, `revision_id`, `update_time`).

3. Tests
   - Existing failing tests are already the right functional spec. After applying the migration and code changes they should pass.
   - Add focused migration tests to assert the new schema elements exist. Examples:
     - `tests/test_common/test_schema_migration_chat_updates.py` — apply migration and assert `threads` table, `messages.deleted`, `attachments.mime_type`, and `message_revisions` columns exist.

4. Workflow (TDD-ish)
   - Add migration file(s) under `migrations/` (one file keeping order consistent with current numbering, e.g. `011_chat_schema_updates.py`).
   - Update application code to use new schema names.
   - Add the migration tests described above.
   - Run the full test suite; fix remaining failures.

Files to add / change
- Add: `migrations/011_chat_schema_updates.py` (or split into multiple migrations if preferred; keep numbering sequential)
- Update: `src/gchat_mirror/exporters/discourse/message_exporter.py`
- Update: `src/gchat_mirror/exporters/discourse/attachment_cache.py`
- Update: `src/gchat_mirror/sync/storage.py`
- Add: `tests/test_common/test_schema_migration_chat_updates.py`

Acceptance criteria
- Running `pytest` completes with 0 failures.
- The `migrations` runner (`run_migrations`) creates a chat DB with the new schema elements.

Risks and notes
- Data-loss risk: the chosen migrations may drop/recreate tables (e.g. `message_revisions`) rather than perform complex in-place migrations. This is acceptable per "no backwards compatibility" decision but should be recorded for operators.
- If the project needs a non-destructive migration later, we should implement a careful in-place migration with backups and transforms.

Estimated effort
- Implement migrations + code updates + tests: ~1–2 hours. Running tests and iterative fixes: additional 15–30 minutes.

Next steps (recommended immediate actions)
1. Create a short-lived branch named `fix/schema-match-tests`.
2. Implement the migration(s) and the minimal code changes listed above.
3. Run `pytest` and iterate until green.
4. Open a PR describing: the schema changes, the lack of backward compatibility, and migration impact on existing databases.

If you want I can implement the migration and code changes now and re-run the test suite — tell me to proceed and I'll push the changes onto a WIP branch and re-run the tests.
