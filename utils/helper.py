import time
import inspect
from functools import wraps
from utils.logger import get_logger
import os
from pathlib import Path
import pathspec


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



def get_ignore_spec(repo_path: Path) -> pathspec.PathSpec:
    """Reads .gitignore and .indexingignore to compile a master PathSpec filter."""
    ignore_lines = []
    
    # 1. Read standard .gitignore (so you don't have to duplicate rules)
    gitignore_path = repo_path / ".gitignore"
    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8") as f:
            ignore_lines.extend(f.readlines())
            
    # 2. Read custom .indexingignore (for LLM-specific overrides)
    indexingignore_path = repo_path / ".indexingignore"
    if indexingignore_path.exists():
        with open(indexingignore_path, "r", encoding="utf-8") as f:
            ignore_lines.extend(f.readlines())
            
    # 3. Always inject universal safety ignores to protect the parser
    universal_ignores = [
        ".git/",
        ".svn/",
        ".venv/",
        "venv/",
        "node_modules/",
        "__pycache__/",
        "*.pyc",
        "*.log",
        ".localgraph/"
    ]
    ignore_lines.extend(universal_ignores)
    
    # Compile the rules using Git's exact wildcard matching logic
    return pathspec.PathSpec.from_lines('gitwildmatch', ignore_lines)