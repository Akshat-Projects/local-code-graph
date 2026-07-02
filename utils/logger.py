"""
Initializes custom logging configuration with rotating file handlers and console output,
providing deep-trace formatting layout for debugging.
"""

import inspect
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Deep trace formatting layout for file capture
LOG_FORMAT = "%(asctime)s | %(levelname)s | [%(filename)s:%(lineno)d -> %(funcName)s()] | %(message)s"
# Clean layout matching standard Uvicorn style
CONSOLE_FORMAT = "INFO:     %(filename)s:%(lineno)d - %(message)s"

def setup_global_logging():
    """Configures the root logger handlers once."""
    root_logger = logging.getLogger("localgraph")
    root_logger.setLevel(logging.DEBUG)
    
    if not root_logger.handlers:
        # File Handler (Always write deep telemetry to app.log)
        file_handler = RotatingFileHandler(
            LOG_DIR / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        # Ensure the file handler records everything
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

        # Console Handler (For standard terminal fallback streams)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        # Ensure the console streams everything to the screen
        console_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(console_handler)

# Initialize standard handlers immediately on module import
setup_global_logging()

def hook_uvicorn_logging():
    """
    Forces Uvicorn's terminal stdout engine to inherit our localgraph logger settings.
    This guarantees custom code logs print inside the active uvicorn terminal console.
    """
    # Grab the active handlers from our master localgraph setup
    localgraph_logger = logging.getLogger("localgraph")
    
    # Target Uvicorn's core internal logging pipelines
    for uvicorn_logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        uv_logger = logging.getLogger(uvicorn_logger_name)
        # Clear default restrictive uvicorn handlers
        uv_logger.handlers = []
        # Attach our custom formatting and streaming handlers directly
        for handler in localgraph_logger.handlers:
            uv_logger.addHandler(handler)
            
        # 2. Keep Uvicorn itself clamped to INFO to avoid HTTP poll spamting
        uv_logger.setLevel(logging.INFO)
        # Prevent logs from double bubbling up to root
        uv_logger.propagate = False

def get_logger() -> logging.Logger:
    """
    Dynamically fetches or creates a logger named after the calling file's module.
    Usage: logger = get_logger()
    """
    frame = inspect.stack()[1]
    module = inspect.getmodule(frame[0])
    
    logger_name = module.__name__ if module else Path(frame.filename).stem
    
    if not logger_name.startswith("localgraph"):
        logger_name = f"localgraph.{logger_name}"
        
    return logging.getLogger(logger_name)

