# ABOUTME: Tests for structured logging setup
# ABOUTME: Validates structlog configuration and logger retrieval

from __future__ import annotations

import io
import json
import sys

import pytest  # type: ignore

from gchat_mirror.common.logging import configure_logging, get_logger


def test_structured_logging_outputs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.StringIO()
    original_stdout = sys.stdout
    monkeypatch.setattr(sys, "stdout", buffer)

    try:
        configure_logging(debug=True)
        logger = get_logger("test")
        logger.info("test_event", key="value", count=3)
    finally:
        monkeypatch.setattr(sys, "stdout", original_stdout)

    log_line = buffer.getvalue().strip().splitlines()[-1]
    data = json.loads(log_line)

    assert data["event"] == "test_event"
    assert data["key"] == "value"
    assert data["count"] == 3
    assert data["level"] == "info"
    assert "timestamp" in data
