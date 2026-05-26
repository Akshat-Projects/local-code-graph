import time
import inspect

from functools import wraps

from utils.logger import get_logger

logger = get_logger()


def timeit(func):
    """
    Measure execution time for both
    sync and async functions.
    """

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):

            start = time.perf_counter()

            result = await func(*args, **kwargs)

            end = time.perf_counter()

            logger.info(
                f"[ASYNC] {func.__name__} "
                f"completed in {(end - start):.4f}s"
            )

            return result

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args, **kwargs):

        start = time.perf_counter()

        result = func(*args, **kwargs)

        end = time.perf_counter()

        logger.info(
            f"[SYNC] {func.__name__} "
            f"completed in {(end - start):.4f}s"
        )

        return result

    return sync_wrapper