from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, Type

import structlog

logger = structlog.get_logger()


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exc = e
                    if attempt == max_retries:
                        break
                    delay = base_delay * (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "retry",
                        func=func.__name__,
                        attempt=attempt + 1,
                        delay=round(delay, 2),
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
