This repository syncs Google Chat <-> Discourse. The goal of these instructions is to give an AI coding assistant just the concrete, discoverable knowledge it needs to be productive: where the real logic lives, how to run and debug locally, and project-specific conventions.

- Top-level architecture (quick)
  - Main coordinator: `src/gchat_discourse/__main__.py` (class: `SyncService`). It wires together:
    - Google Chat client: `src/gchat_discourse/google_chat_client.py` (OAuth flow, token management)
    - Discourse client: `src/gchat_discourse/discourse_client.py` (API-key auth)
    - Sync modules: `sync_gchat_to_discourse.py` and `sync_discourse_to_gchat.py` (core mapping logic)
    - Webhook listener: `webhook_listener.py` (Flask server, registers handlers for post/topic events)
    - DB: `db.py` (SQLite file `sync_db.sqlite`, stores mappings and last-sync timestamps)

- Important entrypoints & run flow
  - Project console script: `gchat-discourse` (defined in `pyproject.toml` as `gchat_discourse.__main__:main`). Running the package or script initializes `SyncService`.
  - Dev helper: `./run.sh` exposes `setup`, `install`, and `run` commands. Typical local workflow:
    - `./run.sh setup` -> copies `config.yaml.example` to `config.yaml` and prints next steps
    - edit `config.yaml` (see example mappings below)
    - `./run.sh install` -> helper to install dependencies (project uses `pyproject.toml` for deps)
    - `./run.sh run` or `python -m gchat_discourse` / `gchat-discourse` to start the service

- Config and secrets (where to look & what matters)
  - Config file: `config.yaml` (template: `config.yaml.example`). `Config` loader is `src/gchat_discourse/config_loader.py` and it strictly validates required sections `discourse`, `google`, `sync_settings`. Missing sections raise errors.
  - Google OAuth: `credentials.json` (OAuth client) and `token.json` (saved token after first run). First-run triggers browser auth; deleting `token.json` forces re-auth.
  - Discourse: `discourse.api_key` + `api_username` set in `config.yaml`.

- Data mappings and loop prevention (critical)
  - Mappings live in `config.yaml` under `mappings` and are persisted at runtime in `sync_db.sqlite`.
  - DB tables (find implementations in `db.py`) include `space_to_category`, `thread_to_topic`, `message_to_post`, and `sync_state`.
  - Loop prevention strategy is implemented in the sync handlers:
    - Skip posts created by the configured `discourse.api_username`
    - Check DB mappings before creating cross-platform entities

- Where the actual sync logic and method names are
  - Initial orchestration: `SyncService.initial_sync()` (in `__main__.py`).
  - Periodic sync scheduler: `SyncService._run_scheduler()` uses `schedule.every(...).minutes` and calls `GChatToDiscourseSync.sync_messages_to_posts()`.
  - Discourse -> GChat webhook handlers call `DiscourseToGChatSync.sync_post_to_message()` and related methods.

- Developer/debugging notes (concrete commands & files)
  - Logs: `sync_service.log` (configured in `__main__` logging setup). Use `tail -f sync_service.log` while reproducing.
  - Inspect DB: `sqlite3 sync_db.sqlite` to view mappings and `sync_state` (or use a GUI). To reset state: `rm sync_db.sqlite` (will force re-sync).
  - OAuth troubleshooting: delete `token.json` and re-run to re-trigger browser auth.
  - Webhook testing: the Flask endpoint expects Discourse webhooks at `/discourse-webhook` (see README/QUICKSTART). For local testing use ngrok and point Discourse webhooks to the ngrok URL.

- Project conventions & gotchas
  - The codebase centralizes configuration in `config_loader.Config` — rely on its properties (e.g. `google_credentials_file`, `discourse_api_key`, `space_mappings`) rather than parsing YAML ad-hoc.
  - The package entrypoint is implemented as a module (`__main__.py`) — tests and scripts should import `gchat_discourse` components and construct `SyncService` directly for deterministic behavior.
  - `pyproject.toml` contains the dependency list and a console script entry; Python runtime requirement is `>=3.13` (use that when reproducing CI/dev environments).

- Quick examples you may reference in code edits
  - Find mapping for a space: use `Config.get_mapping_for_space(space_id)` (see `config_loader.py`).
  - Trigger initial sync in tests: instantiate `SyncService(config_path)` then call `service.initial_sync()` (this avoids running the webhook server).
  - Periodic sync: call `GChatToDiscourseSync.sync_messages_to_posts(space_id, since_timestamp=...)` directly for unit testing.

- Non-goals for the assistant (what NOT to change without human sign-off)
  - Do not commit secrets or tokens (`config.yaml` and `credentials.json` are in `.gitignore` by convention).
  - Major changes to loop-prevention logic or DB schema should be proposed and reviewed — these affect correctness across platforms.

If any section above is unclear or you want more examples (file-level call graphs, common helper functions in `db.py`, or test harness scaffolding), tell me which area to expand and I will update this file.
