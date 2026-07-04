"""
Provides shared utility helper functions and decorators (e.g. execution timer timeit,
path validation, ignore specs processing) used throughout the application.
"""

import time
import inspect
from functools import wraps
from utils.logger import get_logger
from fastapi import HTTPException
import os
from pathlib import Path
import pathspec

from utils.constants import SecurityConstraints


logger = get_logger()

def timeit(_func=None, *, attach_as: str | None = None):
    """
    Measure execution time for sync and async functions.
    If attach_as is given and the function returns a dict,
    the elapsed seconds are written into that key before returning —
    lets LangGraph nodes expose timing through their own state output
    without each node hand-rolling perf_counter() calls.
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                logger.info(f"[ASYNC] {func.__name__} completed in {elapsed:.4f}s")
                if attach_as and isinstance(result, dict):
                    result[attach_as] = elapsed
                return result
            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info(f"[SYNC] {func.__name__} completed in {elapsed:.4f}s")
            if attach_as and isinstance(result, dict):
                result[attach_as] = elapsed
            return result
        return sync_wrapper

    # Supports both bare @timeit and @timeit(attach_as="...")
    if _func is not None:
        return decorator(_func)
    return decorator

# def timeit(func):
#     """
#     Measure execution time for both
#     sync and async functions.
#     """

#     if inspect.iscoroutinefunction(func):

#         @wraps(func)
#         async def async_wrapper(*args, **kwargs):
#             start = time.perf_counter()
#             result = await func(*args, **kwargs)
#             end = time.perf_counter()
#             logger.info(
#                 f"[ASYNC] {func.__name__} "
#                 f"completed in {(end - start):.4f}s"
#             )
#             return result

#         return async_wrapper

#     @wraps(func)
#     def sync_wrapper(*args, **kwargs):
#         start = time.perf_counter()
#         result = func(*args, **kwargs)
#         end = time.perf_counter()
#         logger.info(
#             f"[SYNC] {func.__name__} "
#             f"completed in {(end - start):.4f}s"
#         )
#         return result

#     return sync_wrapper



def get_ignore_spec(repo_path: Path) -> pathspec.PathSpec:
    """Reads .gitignore and .indexingignore to compile a master PathSpec filter."""
    ignore_lines = []
    
    try:
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
    except Exception as e:
        logger.warning(f"Missing `.gitignore` or/and `.indexingignore`: {e}")
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

def validate_ingestion_path(path_str: str) -> Path:
    target_dir = Path(path_str).resolve()

    if not target_dir.exists():
        raise HTTPException(
            status_code=400,
            detail="Path does not exist"
        )

    if not target_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Path is not a directory"
        )

    for forbidden in SecurityConstraints.FORBIDDEN_PATHS:
        try:
            target_dir.relative_to(forbidden)

            raise HTTPException(
                status_code=403,
                detail=f"Forbidden path: {forbidden}"
            )

        except ValueError:
            continue

    return target_dir

def secure_path_join(base_path: str | Path, relative_path: str) -> Path:
    """
    Securely joins a base path and a relative path, resolving any symlinks/traversal
    and ensuring the resolved target path is strictly within the base path.
    """
    base_dir = Path(base_path).resolve()
    
    # Strip leading slashes to prevent absolute path resolution
    safe_rel_path = relative_path.lstrip("\\/")
    
    target_path = (base_dir / safe_rel_path).resolve()
    
    # Ensure target is relative to base
    if not target_path.is_relative_to(base_dir):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Path traversal attempt detected"
        )
    return target_path


def log_ingestion_stats(repo_name: str, duration_ast: float, duration_llm: float, duration_else: float):
    """
    Logs ingestion performance statistics directly to standard application logs.
    """
    def format_time(seconds: float) -> str:
        if seconds >= 60:
            return f"{seconds / 60:.2f} min"
        return f"{seconds:.2f} s"
        
    total_time = duration_ast + duration_llm + duration_else
    stats_message = (
        f"\n--- Ingestion Stats for '{repo_name}' ---\n"
        f"Graph extraction      {format_time(duration_ast)}\n"
        f"LLM                   {format_time(duration_llm)}\n"
        f"Everything else       {format_time(duration_else)}\n"
        f"Total time            {format_time(total_time)}"
    )
    logger.info(stats_message)

