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
    
class NodeTypes:
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    SCRIPT_BLOCK = "script_block"  # Phase 1b addition
    
    # Every consumer that filters by type imports this set
    # instead of hardcoding ["file", "class", "function"]
    STRUCTURAL = {FILE, CLASS, FUNCTION, SCRIPT_BLOCK}
    
    # Ghost-node resurrection and status endpoint skip these
    NON_SUMMARIZABLE = {"library", "infrastructure"}
