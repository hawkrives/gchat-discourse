# ABOUTME: Tests for retry logic with exponential backoff
# ABOUTME: Verifies retry behavior, backoff calculation, and error handling

from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest  # type: ignore

from gchat_mirror.common.retry import RetryConfig, is_retryable_http_error, with_retry


def test_retry_success_after_failures() -> None:
    """Test that retry succeeds after transient failures."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)

    call_count = 0

    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Transient error")
        return "success"

    result = with_retry(config, flaky_function)

    assert result == "success"
    assert call_count == 3


def test_retry_exhausted() -> None:
    """Test that retry gives up after max attempts."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)

    def always_fails():
        raise Exception("Permanent error")

    with pytest.raises(Exception, match="Permanent error"):
        with_retry(config, always_fails)


def test_retry_with_non_retryable() -> None:
    """Test that non-retryable errors fail immediately."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)

    call_count = 0

    def failing_function():
        nonlocal call_count
        call_count += 1
        raise ValueError("Bad input")

    def should_retry(e):
        return not isinstance(e, ValueError)

    with pytest.raises(ValueError):
        with_retry(config, failing_function, should_retry=should_retry)

    assert call_count == 1  # Should not retry


def test_exponential_backoff_calculation() -> None:
    """Test backoff delay calculation."""
    config = RetryConfig(initial_delay=1.0, backoff_factor=2.0, max_delay=10.0)

    assert config.get_delay(0) == 1.0  # 1 * 2^0
    assert config.get_delay(1) == 2.0  # 1 * 2^1
    assert config.get_delay(2) == 4.0  # 1 * 2^2
    assert config.get_delay(3) == 8.0  # 1 * 2^3
    assert config.get_delay(4) == 10.0  # capped at max_delay
    assert config.get_delay(5) == 10.0  # capped at max_delay


def test_is_retryable_http_error_403() -> None:
    """Test that 403 errors are not retryable."""
    response = Mock()
    response.status_code = 403
    error = httpx.HTTPStatusError("Forbidden", request=Mock(), response=response)

    assert is_retryable_http_error(error) is False


def test_is_retryable_http_error_404() -> None:
    """Test that 404 errors are not retryable."""
    response = Mock()
    response.status_code = 404
    error = httpx.HTTPStatusError("Not Found", request=Mock(), response=response)

    assert is_retryable_http_error(error) is False


def test_is_retryable_http_error_429() -> None:
    """Test that 429 rate limit errors are retryable."""
    response = Mock()
    response.status_code = 429
    error = httpx.HTTPStatusError("Too Many Requests", request=Mock(), response=response)

    assert is_retryable_http_error(error) is True


def test_is_retryable_http_error_500() -> None:
    """Test that 500 errors are retryable."""
    response = Mock()
    response.status_code = 500
    error = httpx.HTTPStatusError("Internal Server Error", request=Mock(), response=response)

    assert is_retryable_http_error(error) is True


def test_is_retryable_http_error_503() -> None:
    """Test that 503 errors are retryable."""
    response = Mock()
    response.status_code = 503
    error = httpx.HTTPStatusError("Service Unavailable", request=Mock(), response=response)

    assert is_retryable_http_error(error) is True


def test_is_retryable_timeout_error() -> None:
    """Test that timeout errors are retryable."""
    error = httpx.TimeoutException("Request timeout")

    assert is_retryable_http_error(error) is True


def test_is_retryable_network_error() -> None:
    """Test that network errors are retryable."""
    error = httpx.NetworkError("Connection failed")

    assert is_retryable_http_error(error) is True


def test_is_retryable_connect_error() -> None:
    """Test that connect errors are retryable."""
    error = httpx.ConnectError("Connection refused")

    assert is_retryable_http_error(error) is True


def test_is_retryable_http_error_400() -> None:
    """Test that 400 bad request errors are not retryable."""
    response = Mock()
    response.status_code = 400
    error = httpx.HTTPStatusError("Bad Request", request=Mock(), response=response)

    assert is_retryable_http_error(error) is False


def test_retry_uses_should_retry_with_http_errors() -> None:
    """Test that with_retry respects should_retry for HTTP errors."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)

    call_count = 0

    def failing_with_403():
        nonlocal call_count
        call_count += 1
        response = Mock()
        response.status_code = 403
        raise httpx.HTTPStatusError("Forbidden", request=Mock(), response=response)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(config, failing_with_403, should_retry=is_retryable_http_error)

    # Should not retry 403
    assert call_count == 1


def test_retry_with_retryable_http_error() -> None:
    """Test that with_retry retries on retryable HTTP errors."""
    config = RetryConfig(max_attempts=3, initial_delay=0.01)

    call_count = 0

    def failing_with_503():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            response = Mock()
            response.status_code = 503
            raise httpx.HTTPStatusError("Service Unavailable", request=Mock(), response=response)
        return "success"

    result = with_retry(config, failing_with_503, should_retry=is_retryable_http_error)

    assert result == "success"
    assert call_count == 3
