# ABOUTME: Tests for configuration utilities
# ABOUTME: Ensures TOML loading and environment overrides work

from __future__ import annotations

from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.config import (
    _deep_merge,
    apply_env_overrides,
    get_default_sync_config,
    load_config,
)


def test_load_config_from_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[auth]
credential_key = "test-key"

[sync]
initial_sync_days = 30
""")

    config = load_config(config_file)

    assert config["auth"]["credential_key"] == "test-key"
    assert config["sync"]["initial_sync_days"] == 30


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[sync]
initial_sync_days = 90
""")

    monkeypatch.setenv("GCHAT_MIRROR_SYNC_INITIAL_SYNC_DAYS", "30")
    config = load_config(config_file)

    assert config["sync"]["initial_sync_days"] == 30


def test_deep_merge() -> None:
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 10}, "e": 4}

    merged = _deep_merge(base, override)

    assert merged["a"]["b"] == 10
    assert merged["a"]["c"] == 2
    assert merged["d"] == 3
    assert merged["e"] == 4


def test_apply_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    config = {"sync": {"initial_sync_days": 90}}

    monkeypatch.setenv("GCHAT_MIRROR_SYNC_DOWNLOAD_WORKERS", "4")
    updated = apply_env_overrides(config)

    assert updated["sync"]["download_workers"] == 4


def test_get_default_sync_config() -> None:
    defaults = get_default_sync_config()

    assert defaults["auth"]["credential_key"] == "gchat-sync"
    assert "sync" in defaults
    assert "monitoring" in defaults
