# GChat Mirror

Mirror Google Chat data into a local SQLite database and prepare it for export workflows like Discourse.

## Features

- Google OAuth credential loading with keyring persistence
- SQLite schema and migration system for spaces, users, memberships, and messages
- Sync daemon that polls spaces and stores messages with structlog-based telemetry
- CLI entry point with sync controls and placeholder export and client commands
- Comprehensive test suite, including end-to-end sync coverage with mocked APIs

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management
- Google Cloud project with the Chat API enabled and OAuth credentials

## Installation

```bash
# Clone the repository
git clone https://github.com/hawkrives/gchat-discourse.git
cd gchat-discourse

# Install dependencies
uv sync

# (Optional) install development extras
uv pip install -e ".[dev]"
```

## Configuration

1. Create a Google OAuth client (Desktop application) and download the credentials JSON as `client_secrets.json` in the repository root.
2. Place sync configuration in `~/.config/gchat-mirror/sync/config.toml`:

```toml
[auth]
credential_key = "gchat-sync"

[sync]
initial_sync_days = 90

[monitoring]
health_check_port = 4981
```

3. Override any value with environment variables using the `GCHAT_MIRROR_*` prefix, for example:

```bash
export GCHAT_MIRROR_SYNC_INITIAL_SYNC_DAYS=30
```

Sync state is stored under `~/.local/share/gchat-mirror/sync/chat.db` by default; adjust with the `--data-dir` option.

## Usage

```bash
# Start the sync daemon (will trigger OAuth on first run)
uv run gchat-mirror sync start

# Show sync status (database counts and size)
uv run gchat-mirror sync status

# Show CLI help
uv run gchat-mirror --help
```

CLI placeholders:

- `gchat-mirror export discourse start|status` – reserved for Phase 4
- `gchat-mirror clients list|unregister` – reserved for Phase 2

## Development

```bash
# Run the full test suite
uv run pytest

# Format and lint
uv run ruff format
uv run ruff check
```

Key directories:

- `src/gchat_mirror/common` – shared infrastructure (migrations, database, config, logging)
- `src/gchat_mirror/sync` – sync daemon, auth, Google Chat client, storage
- `src/gchat_mirror/cli` – CLI entry point and command groups
- `migrations` – SQLite schema migrations
- `tests` – unit and integration tests covering the system

## License

GPL-3.0-only
