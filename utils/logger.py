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

# import inspect
# import logging
# from logging.handlers import RotatingFileHandler
# from pathlib import Path

# LOG_DIR = Path("logs")
# LOG_DIR.mkdir(exist_ok=True)

# # 1. Create a master format string that explicitly tracks the file, function, and line number
# LOG_FORMAT = "%(asctime)s | %(levelname)s | [%(filename)s:%(lineno)d -> %(funcName)s()] | %(message)s"
# CONSOLE_FORMAT = "%(level_prefix)s%(filename)s:%(lineno)d - %(message)s"

# class CleanNewlineFormatter(logging.Formatter):
#     """
#     Custom formatter that handles leading and trailing newlines in messages by
#     moving them to the outside of the formatted log line, keeping the log metadata
#     on the same line as the message content.
#     """
#     def format(self, record):
#         orig_msg = record.msg
#         leading_newlines = ""
#         trailing_newlines = ""
        
#         if isinstance(record.msg, str):
#             # Capture leading newlines
#             stripped_leading = record.msg.lstrip("\n")
#             if len(stripped_leading) < len(record.msg):
#                 leading_newlines = "\n" * (len(record.msg) - len(stripped_leading))
            
#             # Capture trailing newlines from the already left-stripped message
#             stripped_both = stripped_leading.rstrip("\n")
#             if len(stripped_both) < len(stripped_leading):
#                 trailing_newlines = "\n" * (len(stripped_leading) - len(stripped_both))
                
#             record.msg = stripped_both
            
#         formatted = super().format(record)
#         record.msg = orig_msg
        
#         return f"{leading_newlines}{formatted}{trailing_newlines}"

# class ConsoleFormatter(CleanNewlineFormatter):
#     """
#     Console formatter that dynamically prefixes logs with aligned level names
#     (e.g., 'INFO:    ', 'WARNING: ', 'ERROR:   ') to match Uvicorn style.
#     """
#     def format(self, record):
#         level = record.levelname
#         prefix = f"{level}:"
#         record.level_prefix = f"{prefix:<9}"
#         return super().format(record)

# def setup_global_logging():
#     """Configures the root logger handlers once."""
#     root_logger = logging.getLogger("localgraph")
#     root_logger.setLevel(logging.INFO)
    
#     # Prevent duplicate handlers if setup is called multiple times
#     if not root_logger.handlers:
#         # File Handler
#         file_handler = RotatingFileHandler(
#             LOG_DIR / "app.log",
#             maxBytes=5 * 1024 * 1024,
#             backupCount=5
#         )
#         file_handler.setFormatter(CleanNewlineFormatter(LOG_FORMAT))
#         root_logger.addHandler(file_handler)

#         # Console Handler
#         console_handler = logging.StreamHandler()
#         console_handler.setFormatter(ConsoleFormatter(CONSOLE_FORMAT))
#         root_logger.addHandler(console_handler)

# # Initialize handlers on module load
# setup_global_logging()

# def get_logger() -> logging.Logger:
#     """
#     Dynamically fetches or creates a logger named after the calling file's module.
#     Usage: logger = get_logger()
#     """
#     # Look back 1 step in the execution stack to find who called get_logger()
#     frame = inspect.stack()[1]
#     module = inspect.getmodule(frame[0])
    
#     # Fallback to the file base name if module name isn't cleanly resolved
#     logger_name = module.__name__ if module else Path(frame.filename).stem
    
#     # Ensure it becomes a child of the main 'localgraph' logger for handler inheritance
#     if not logger_name.startswith("localgraph"):
#         logger_name = f"localgraph.{logger_name}"
        
#     return logging.getLogger(logger_name)

# import logging
# from logging.handlers import RotatingFileHandler
# from pathlib import Path

# LOG_DIR = Path("logs")
# LOG_DIR.mkdir(exist_ok=True)

# logger = logging.getLogger("local-graph-rag")
# logger.setLevel(logging.INFO)

# handler = RotatingFileHandler(
#     LOG_DIR / "app.log",
#     maxBytes=5 * 1024 * 1024,
#     backupCount=5
# )

# formatter = logging.Formatter(
#     "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
# )

# handler.setFormatter(formatter)

# logger.addHandler(handler)