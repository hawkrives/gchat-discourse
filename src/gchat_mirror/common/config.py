# ABOUTME: Configuration loading helpers
# ABOUTME: Handles TOML configs and environment overrides

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

import tomllib


def load_config(config_path: Path, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load configuration from TOML file with environment overrides."""
    config = defaults.copy() if defaults else {}

    if config_path.exists():
        with config_path.open("rb") as fh:
            file_data = tomllib.load(fh)
        config = _deep_merge(config, file_data)

    return apply_env_overrides(config)


def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to config."""
    result = deepcopy(config)
    prefix = "GCHAT_MIRROR_"

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue

        segments = _split_env_key(key[len(prefix) :])
        if not segments:
            continue

        current: Dict[str, Any] = result
        for part in segments[:-1]:
            current = current.setdefault(part, {})

        current[segments[-1]] = _parse_env_value(value)

    return result


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def get_default_sync_config() -> Dict[str, Any]:
    """Get default configuration for sync daemon."""
    return {
        "auth": {
            "credential_key": "gchat-sync",
        },
        "sync": {
            "initial_sync_days": 90,
            "active_space_poll_seconds": 10,
            "quiet_space_poll_minutes": 5,
            "download_workers": None,
        },
        "monitoring": {
            "health_check_port": 4981,
        },
    }


def _parse_env_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        return int(value)
    except ValueError:
        return value


def _split_env_key(raw_key: str) -> list[str]:
    key = raw_key.strip("_")
    if not key:
        return []

    if "__" in key:
        return [segment.lower() for segment in key.split("__") if segment]

    pieces = key.split("_")
    if len(pieces) == 1:
        return [pieces[0].lower()]

    return [pieces[0].lower(), "_".join(pieces[1:]).lower()]
