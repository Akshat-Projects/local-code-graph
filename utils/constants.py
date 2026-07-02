"""
Defines system-wide static constants for LocalGraph AI, including security constraints,
ignored stopwords, language extensions, and network node properties.
"""

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

    STOP_WORDS = {
            "why", "is", "my", "chatbot", "not", "find", "any", "mentions", "of", 
            "despite", "me", "adding", "regex", "search", "in", "whole", "code", 
            "base", "can", "you", "see", "where", "the", "does", "do", "how", "what", 
            "which", "who", "whom", "this", "that", "these", "those", "am", "are", 
            "was", "were", "be", "been", "being", "have", "has", "had", "having", 
            "a", "an", "and", "but", "if", "or", "because", "as", "until", "while", 
            "at", "by", "for", "with", "about", "against", "between", "into", "through", 
            "during", "before", "after", "above", "below", "to", "from", "up", "down", 
            "on", "off", "over", "under", "again", "further", "then", "once", "here", 
            "there", "when", "all", "both", "each", "few", "more", "most", "other", 
            "some", "such", "no", "nor", "only", "own", "same", "so", "than", "too", 
            "very", "will", "just", "should", "now", "us", "use", "used", "using",
            "tell", "give", "code", "related", "write", "show", "get", "find", "make", 
            "explain", "describe", "detail", "summary", "list", "check", "verify", 
            "run", "execute", "test", "implementation", "implement", "add", "change", 
            "create", "delete", "remove", "update", "modify", "patch", "fix", "bug", 
            "issue", "error", "exception", "crash", "fail", "failure", "success", 
            "work", "can", "could", "should", "would", "must", "may", "might", "shall", 
            "please", "thanks", "thank", "hello", "hi", "hey", "dear", "sir", "madam", 
            "ai", "assistant", "bot", "chat", "chatbot", "history", "message", "query", 
            "question", "input", "output", "result", "response", "answer", "context", 
            "payload", "file", "folder", "directory", "repo", "repository", "workspace", 
            "codebase", "project", "source", "structure", "snippet", "snippets",
            "about", "also", "some", "someone", "something", "somewhere", "anyone",
            "anything", "anywhere", "noone", "nothing", "nowhere", "everyone", 
            "everything", "everywhere", "more", "most", "less", "least", "few", 
            "many", "several", "much", "little", "own", "other", "another", "such",
            "different", "similar", "like", "as", "than", "too", "very", "quite", 
            "rather", "somewhat", "highly", "extremely", "really"
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
