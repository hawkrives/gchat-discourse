# ABOUTME: Tests for Google Chat authentication helpers
# ABOUTME: Validates credential loading, refreshing, and storage

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.sync import auth


def test_save_and_load_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    storage: dict[str, str] = {}

    def fake_set_password(service: str, key: str, value: str) -> None:
        storage[key] = value

    def fake_get_password(service: str, key: str) -> str | None:
        return storage.get(key)

    monkeypatch.setattr(auth.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(auth.keyring, "get_password", fake_get_password)

    creds = auth.Credentials(
        token="token",
        refresh_token="refresh",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client",
        client_secret="secret",
    )

    auth.save_credentials("test-key", creds)
    loaded = auth.load_credentials("test-key")

    assert loaded is not None
    assert loaded.token == "token"
    assert loaded.refresh_token == "refresh"


def test_authenticate_returns_existing_valid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_creds = Mock()
    valid_creds.valid = True

    monkeypatch.setattr(auth, "load_credentials", lambda key: valid_creds)

    result = auth.authenticate("test-key")
    assert result is valid_creds


def test_authenticate_refreshes_expired_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    refreshed = Mock()
    refreshed.valid = False
    refreshed.expired = True
    refreshed.refresh_token = "refresh"

    def fake_refresh(request: Any) -> None:
        refreshed.valid = True

    refreshed.refresh = fake_refresh

    monkeypatch.setattr(auth, "load_credentials", lambda key: refreshed)

    saved: dict[str, auth.Credentials] = {}

    def fake_save(key: str, creds: auth.Credentials) -> None:
        saved[key] = creds

    monkeypatch.setattr(auth, "save_credentials", fake_save)
    monkeypatch.setattr(auth, "Request", Mock())

    result = auth.authenticate("test-key")

    assert result is refreshed
    assert saved["test-key"] is refreshed


def test_authenticate_runs_oauth_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(auth, "load_credentials", lambda key: None)

    flow = Mock()
    flow.run_local_server.return_value = Mock()

    mock_factory = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", mock_factory)

    saved: dict[str, auth.Credentials] = {}
    monkeypatch.setattr(auth, "save_credentials", lambda key, creds: saved.setdefault(key, creds))

    monkeypatch.chdir(tmp_path)
    (tmp_path / "client_secrets.json").write_text("{}")

    result = auth.authenticate("test-key")

    assert result is flow.run_local_server.return_value
    assert saved["test-key"] is result
    mock_factory.assert_called_once()
