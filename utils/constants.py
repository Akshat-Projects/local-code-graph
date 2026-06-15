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
    
class AllowedTypes():
    SUPPORTED_EXTENSIONS = {
    ".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".java", ".rs", ".go", ".php", ".c", ".h", ".cpp", ".hpp", 
    ".cs", ".rb", ".swift", ".kt", ".r", ".sql", ".json", ".yaml",
    ".yml", '.txt', '.toml'
    }
