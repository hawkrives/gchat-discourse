from datetime import datetime, timezone

from gchat_mirror.exporters.discourse.retry_config import RetryConfig


def test_retry_config_exponential_backoff():
    """Test exponential backoff calculation."""
    config = RetryConfig(
        initial_delay=60,
        backoff_multiplier=2.0,
        max_delay=3600
    )
    
    # First retry: ~60 seconds
    next_retry = config.calculate_next_retry(error_count=1)
    delay = (next_retry - datetime.now(timezone.utc)).total_seconds()
    assert 50 < delay < 70  # Allow for jitter
    
    # Second retry: ~120 seconds
    next_retry = config.calculate_next_retry(error_count=2)
    delay = (next_retry - datetime.now(timezone.utc)).total_seconds()
    assert 100 < delay < 140
    
    # Third retry: ~240 seconds
    next_retry = config.calculate_next_retry(error_count=3)
    delay = (next_retry - datetime.now(timezone.utc)).total_seconds()
    assert 200 < delay < 280


def test_retry_config_max_delay():
    """Test that delay is capped at maximum."""
    config = RetryConfig(
        initial_delay=60,
        backoff_multiplier=2.0,
        max_delay=300
    )
    
    # High error count should still cap at max_delay
    next_retry = config.calculate_next_retry(error_count=10)
    delay = (next_retry - datetime.now(timezone.utc)).total_seconds()
    assert delay <= 330  # max_delay + jitter


def test_retry_config_max_attempts():
    """Test max attempts check."""
    config = RetryConfig(max_attempts=5)
    
    assert config.should_retry(1) == True
    assert config.should_retry(4) == True
    assert config.should_retry(5) == False
    assert config.should_retry(10) == False


def test_retry_config_permanent_failure_detection():
    """Test permanent vs temporary failure detection."""
    config = RetryConfig()
    
    # Permanent failures
    assert config.is_permanent_failure("404 Not Found") == True
    assert config.is_permanent_failure("403 Forbidden") == True
    assert config.is_permanent_failure("ValidationError: Invalid username") == True
    
    # Temporary failures
    assert config.is_permanent_failure("429 Rate Limited") == False
    assert config.is_permanent_failure("500 Internal Server Error") == False
    assert config.is_permanent_failure("Connection timeout") == False
