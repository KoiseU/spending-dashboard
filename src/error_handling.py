"""
Error Handling and Retry Logic

Provides:
- Retry decorators with exponential backoff
- Circuit breaker pattern for external services
- Graceful degradation helpers
- Exception context managers
"""

import time
import functools
from typing import Callable, Type, Tuple, Optional
from datetime import datetime, timedelta

from src.logger import setup_logger

logger = setup_logger(__name__)


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    Retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for each retry (exponential backoff)
        exceptions: Tuple of exceptions to catch and retry
        on_retry: Optional callback function called on each retry

    Usage:
        @retry_with_backoff(max_attempts=3, initial_delay=2.0)
        def fetch_data():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(
                            f"Failed after {max_attempts} attempts: {func.__name__}",
                            extra={'function': func.__name__, 'attempts': max_attempts},
                            exc_info=True
                        )
                        raise

                    logger.warning(
                        f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.1f}s...",
                        extra={
                            'function': func.__name__,
                            'attempt': attempt,
                            'max_attempts': max_attempts,
                            'delay': delay,
                            'error': str(e)
                        }
                    )

                    if on_retry:
                        on_retry(attempt, e)

                    time.sleep(delay)
                    delay *= backoff_factor

        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern for external service calls.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests fail immediately
    - HALF_OPEN: Testing if service recovered

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, timeout=60)

        @breaker
        def call_external_api():
            ...
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting half-open
            expected_exceptions: Exceptions that count as failures
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exceptions = expected_exceptions

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def __call__(self, func):
        """Decorator to apply circuit breaker."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                    logger.info(
                        f"Circuit breaker HALF_OPEN for {func.__name__}",
                        extra={'function': func.__name__, 'state': 'HALF_OPEN'}
                    )
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker is OPEN for {func.__name__}. "
                        f"Service unavailable."
                    )

            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result

            except self.expected_exceptions as e:
                self._on_failure()
                raise

        return wrapper

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return (datetime.now() - self.last_failure_time).total_seconds() >= self.timeout

    def _on_success(self):
        """Handle successful call."""
        if self.state == "HALF_OPEN":
            logger.info("Circuit breaker CLOSED (recovered)")
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                f"Circuit breaker OPEN after {self.failure_count} failures",
                extra={'failure_count': self.failure_count, 'state': 'OPEN'}
            )


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class GracefulDegradation:
    """
    Context manager for graceful degradation of non-critical features.

    Usage:
        with GracefulDegradation("email_sending", default_value=False):
            send_email()

        # If send_email() fails, the error is logged but not raised
    """

    def __init__(
        self,
        feature_name: str,
        default_value: any = None,
        log_level: str = "WARNING"
    ):
        """
        Initialize graceful degradation context.

        Args:
            feature_name: Name of the feature for logging
            default_value: Value to return on failure
            log_level: Log level for failures (WARNING, ERROR)
        """
        self.feature_name = feature_name
        self.default_value = default_value
        self.log_level = log_level.upper()
        self.exception = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.exception = exc_val

            log_method = {
                'DEBUG': logger.debug,
                'INFO': logger.info,
                'WARNING': logger.warning,
                'ERROR': logger.error,
                'CRITICAL': logger.critical,
            }.get(self.log_level, logger.warning)

            log_method(
                f"Feature '{self.feature_name}' failed gracefully: {exc_val}",
                extra={'feature': self.feature_name, 'error': str(exc_val)},
                exc_info=True
            )

            # Suppress the exception
            return True

        return False

    def get_result(self):
        """Get the default value if an exception occurred."""
        if self.exception:
            return self.default_value
        return None


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


def with_timeout(seconds: float):
    """
    Decorator to add timeout to a function (Unix/Linux only).

    Note: Uses signal.alarm() which only works on Unix-like systems.
    For cross-platform timeout, consider using concurrent.futures.

    Args:
        seconds: Timeout in seconds

    Usage:
        @with_timeout(30)
        def slow_operation():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError(f"{func.__name__} timed out after {seconds}s")

            # Set the signal handler and alarm
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(seconds))

            try:
                result = func(*args, **kwargs)
            finally:
                # Restore the old handler and cancel the alarm
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            return result

        return wrapper
    return decorator


# Example usage and testing
if __name__ == "__main__":
    # Test retry decorator
    @retry_with_backoff(max_attempts=3, initial_delay=0.1)
    def flaky_function(fail_count=[0]):
        fail_count[0] += 1
        if fail_count[0] < 3:
            raise ValueError(f"Attempt {fail_count[0]} failed")
        return "success"

    print("Testing retry decorator...")
    result = flaky_function()
    print(f"Result: {result}")

    # Test circuit breaker
    breaker = CircuitBreaker(failure_threshold=3, timeout=2)

    @breaker
    def failing_service(should_fail=True):
        if should_fail:
            raise ConnectionError("Service unavailable")
        return "success"

    print("\nTesting circuit breaker...")
    for i in range(5):
        try:
            failing_service()
        except Exception as e:
            print(f"Attempt {i+1}: {e}")

    # Test graceful degradation
    print("\nTesting graceful degradation...")
    with GracefulDegradation("optional_feature", default_value="fallback"):
        raise ValueError("Feature failed")

    print("Graceful degradation successful")
