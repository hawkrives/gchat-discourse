# ABOUTME: Retry configuration for failed Discourse exports
# ABOUTME: Implements exponential backoff and retry limits

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import structlog

logger = structlog.get_logger()

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    
    # Initial retry delay (seconds)
    initial_delay: int = 60
    
    # Maximum retry delay (seconds)
    max_delay: int = 3600  # 1 hour
    
    # Backoff multiplier
    backoff_multiplier: float = 2.0
    
    # Maximum retry attempts
    max_attempts: int = 10
    
    # Jitter percentage (0.0-1.0)
    jitter: float = 0.1

    def calculate_next_retry(self, error_count: int) -> datetime:
        """
        Calculate next retry time based on error count.
        
        Args:
            error_count: Number of previous failures
        
        Returns:
            Datetime for next retry attempt
        """
        import random
        
        # Calculate base delay with exponential backoff
        delay = self.initial_delay * (self.backoff_multiplier ** (error_count - 1))
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to prevent thundering herd
        jitter_amount = delay * self.jitter
        delay = delay + random.uniform(-jitter_amount, jitter_amount)
        
        # Ensure positive delay
        delay = max(delay, 1)
        
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
        
        logger.debug("retry_scheduled",
                    error_count=error_count,
                    delay_seconds=int(delay),
                    next_retry=next_retry.isoformat())
        
        return next_retry
    
    def should_retry(self, error_count: int) -> bool:
        """Check if we should retry based on attempt count."""
        return error_count < self.max_attempts
    
    def is_permanent_failure(self, error_message: str) -> bool:
        """
        Determine if an error is permanent (should not retry).
        
        Permanent failures:
        - 404 Not Found (resource doesn't exist)
        - 403 Forbidden (permission denied)
        - 400 Bad Request (invalid data)
        - ValidationError
        
        Temporary failures:
        - 429 Rate Limited
        - 500 Server Error
        - Network errors
        - Timeouts
        """
        permanent_patterns = [
            "404",
            "Not Found",
            "403",
            "Forbidden",
            "400",
            "Bad Request",
            "ValidationError",
            "Invalid",
            "does not exist"
        ]
        
        for pattern in permanent_patterns:
            if pattern.lower() in error_message.lower():
                logger.info("permanent_failure_detected",
                           error=error_message,
                           pattern=pattern)
                return True
        
        return False
