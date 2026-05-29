from pathlib import Path

class SecurityConstraints():
    FORBIDDEN_PATHS = [
        Path("/etc"),
        Path("/proc"),
        Path("/sys"),
        Path("/dev"),
        Path("/run"),
        Path("/boot"),
            ]
    
    MAX_FILES = 10000
    ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:8501",
        ]