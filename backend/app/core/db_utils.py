"""
db_utils.py — Async retry decorator for resilient database operations.

Provides an `async_retry` decorator that retries failed coroutines with
exponential backoff. Use this to wrap critical DB calls that may fail
transiently during startup (e.g. connection not yet ready).
"""
import asyncio
import functools
from typing import Callable, Type, Tuple
import structlog  # type: ignore

log = structlog.get_logger()


def async_retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
):
    """
    Decorator that retries an async function on failure with exponential backoff.

    Args:
        max_attempts:   Maximum number of total attempts (default 3).
        initial_delay:  Seconds to wait before the first retry (default 1.0).
        max_delay:      Maximum seconds to wait between retries (default 2.0).
        backoff_factor: Multiplier applied to the delay after each failure (default 2.0).
        exceptions:     Tuple of exception types that trigger a retry (default: all).

    Usage::

        @async_retry(max_attempts=3, initial_delay=1.0, max_delay=2.0)
        async def my_db_operation():
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc: BaseException | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        log.error(
                            "async_retry: all attempts exhausted",
                            func=func.__name__,
                            attempts=max_attempts,
                            error=str(exc),
                        )
                        raise
                    log.warning(
                        "async_retry: attempt failed, retrying",
                        func=func.__name__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        retry_in_seconds=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Should never reach here, but satisfies type checkers.
            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator
