Integration tests are manual and may require credentials.

Run them with:

```bash
uv run pytest tests/integration -m integration -q
```

Re-record fixtures using the project's httpx recording utilities when necessary.
