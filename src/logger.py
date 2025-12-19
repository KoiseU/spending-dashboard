"""
Structured Logging Module

Provides centralized, production-grade logging with support for:
- Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Structured JSON output for log aggregation
- Masked sensitive data (credentials, tokens)
- Performance timing decorators
"""

import logging
import sys
import json
import time
import functools
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime


class MaskingFormatter(logging.Formatter):
    """Custom formatter that masks sensitive information."""

    SENSITIVE_KEYS = {
        'password', 'secret', 'token', 'api_key', 'access_token',
        'client_id', 'client_secret', 'plaid_secret', 'smtp_password'
    }

    def mask(self, s: str) -> str:
        """Mask a string, showing only first and last 4 characters."""
        if not s or len(s) <= 8:
            return "***"
        return f"{s[:4]}...{s[-4:]}"

    def mask_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask sensitive keys in a dictionary."""
        if not isinstance(data, dict):
            return data

        masked = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(sensitive in key_lower for sensitive in self.SENSITIVE_KEYS):
                masked[key] = self.mask(str(value)) if value else "***"
            elif isinstance(value, dict):
                masked[key] = self.mask_dict(value)
            elif isinstance(value, list):
                masked[key] = [self.mask_dict(v) if isinstance(v, dict) else v for v in value]
            else:
                masked[key] = value
        return masked

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with masking applied."""
        # Mask any dict-like extra fields
        if hasattr(record, '__dict__'):
            for key in list(record.__dict__.keys()):
                if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                             'levelname', 'levelno', 'lineno', 'module', 'msecs',
                             'pathname', 'process', 'processName', 'relativeCreated',
                             'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info']:
                    value = getattr(record, key)
                    if isinstance(value, dict):
                        setattr(record, key, self.mask_dict(value))
                    elif isinstance(value, str) and any(s in key.lower() for s in self.SENSITIVE_KEYS):
                        setattr(record, key, self.mask(value))

        return super().format(record)


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'pathname', 'process', 'processName', 'relativeCreated',
                          'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info',
                          'message', 'asctime']:
                log_data[key] = value

        return json.dumps(log_data, default=str)


def setup_logger(
    name: str = "financial_dashboard",
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    json_format: bool = False,
    mask_sensitive: bool = True
) -> logging.Logger:
    """
    Set up a logger with console and optional file output.

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output
        json_format: If True, use JSON formatter (useful for log aggregation)
        mask_sensitive: If True, mask sensitive information

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if json_format:
        console_formatter = JSONFormatter()
    else:
        if mask_sensitive:
            console_formatter = MaskingFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        else:
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)

        if json_format:
            file_formatter = JSONFormatter()
        else:
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def timed(logger: Optional[logging.Logger] = None):
    """
    Decorator to log execution time of functions.

    Usage:
        @timed(logger)
        def my_function():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            _logger = logger or logging.getLogger(func.__module__)

            try:
                _logger.debug(f"Starting {func.__name__}")
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                _logger.info(
                    f"Completed {func.__name__}",
                    extra={'elapsed_seconds': round(elapsed, 3), 'function': func.__name__}
                )
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                _logger.error(
                    f"Failed {func.__name__}: {str(e)}",
                    extra={'elapsed_seconds': round(elapsed, 3), 'function': func.__name__},
                    exc_info=True
                )
                raise

        return wrapper
    return decorator


# Create default logger instance
default_logger = setup_logger()


if __name__ == "__main__":
    # Demo usage
    logger = setup_logger("demo", level=logging.DEBUG)

    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning")
    logger.error("This is an error")

    # Test masking
    logger.info("Credentials", extra={
        'api_key': 'sk-1234567890abcdef',
        'password': 'my_secret_password',
        'username': 'john_doe'
    })

    # Test timing decorator
    @timed(logger)
    def slow_function():
        time.sleep(1)
        return "done"

    slow_function()
