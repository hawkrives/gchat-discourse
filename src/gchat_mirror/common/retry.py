# ABOUTME: Retry logic with exponential backoff for API calls
# ABOUTME: Handles transient failures with progressive delays

from __future__ import annotations

import time
from typing import Callable, Optional, TypeVar

import httpx
import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 300.0,
        backoff_factor: float = 2.0,
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-indexed)."""
        delay = self.initial_delay * (self.backoff_factor**attempt)
        return min(delay, self.max_delay)


def with_retry(
    config: RetryConfig,
    func: Callable[[], T],
    should_retry: Optional[Callable[[Exception], bool]] = None,
) -> T:
    """
    Execute function with retry logic.

    Args:
        config: Retry configuration
        func: Function to execute
        should_retry: Optional predicate to determine if exception is retryable

    Returns:
        Result of func()

    Raises:
        Last exception if all retries exhausted
    """
    last_exception: Optional[Exception] = None

    for attempt in range(config.max_attempts):
        try:
            return func()

        except Exception as e:
            last_exception = e

            # Check if we should retry this exception
            if should_retry and not should_retry(e):
                logger.info("exception_not_retryable", error=str(e))
                raise

            # Check if we have more attempts
            if attempt + 1 >= config.max_attempts:
                logger.error("max_retries_exceeded", attempts=config.max_attempts, error=str(e))
                raise

            # Calculate delay
            delay = config.get_delay(attempt)

            logger.warning(
                "retry_after_error",
                attempt=attempt + 1,
                max_attempts=config.max_attempts,
                delay_seconds=delay,
                error=str(e),
            )

            time.sleep(delay)

    # Should never reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry loop completed without result or exception")


def is_retryable_http_error(exception: Exception) -> bool:
    """Determine if an HTTP error is retryable."""
    if not isinstance(exception, httpx.HTTPStatusError):
        # Network errors, timeouts are retryable
        return isinstance(exception, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError))

    # 403 and 404 are not retryable (access denied / not found)
    if exception.response.status_code in (403, 404):
        return False

    # 429 (rate limit) is retryable
    if exception.response.status_code == 429:
        return True

    # 5xx errors are retryable
    if exception.response.status_code >= 500:
        return True

    # 4xx client errors (except 429) are not retryable
    if exception.response.status_code >= 400:
        return False

    return True
