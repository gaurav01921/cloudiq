import time
from collections.abc import Callable


def retry_call(
    fn: Callable,
    attempts: int,
    base_delay_seconds: float,
    retryable_exceptions: tuple[type[BaseException], ...],
):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retryable_exceptions as exc:  # type: ignore[arg-type]
            last_exc = exc
            if attempt == attempts:
                raise
            time.sleep(base_delay_seconds * attempt)
    if last_exc:
        raise last_exc
