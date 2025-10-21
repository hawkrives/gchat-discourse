# User guide

macOS Keychain quickstart
-------------------------

We recommend storing OAuth tokens and API keys in the macOS keychain using the
`keyring` package. This project provides a tiny helper at
`src/gchat_mirror/common/auth_keychain.py` with `store_secret(service, username, secret)`
and `fetch_secret(service, username)` functions.

Example (Python REPL):

```python
from gchat_mirror.common.auth_keychain import store_secret, fetch_secret

store_secret('gchat-mirror', 'discourse_api_key', 'abcd1234')
print(fetch_secret('gchat-mirror', 'discourse_api_key'))
```

Security notes
- Never commit token files like `token.json` or API keys into git.
- Keychain entries are per-user. CI environments should use environment variables.

Quick references
----------------

Run unit tests (fast):

```bash
uv run pytest -k "not integration" -q
```

Run all tests (including integration — manual):

```bash
uv run pytest -q
```

Migration-check script
----------------------

Use the included migration checker to run all migrations against a temporary database and print resulting schema. This is safe and does not modify repo files.

```bash
python tools/check_migrations.py
```

Metrics endpoint
----------------

The health server serves metrics at `http://localhost:4981/metrics` when the daemon is running. It returns Prometheus exposition format including legacy and current metric names.

Quick check (local dev):

```bash
# using curl
curl -s http://localhost:4981/metrics | head -n 50
```

