from core.librarian import Librarian
from core.ast_parser import CodebaseASTParser
from core.universal_parser import UniversalParser
from config import settings
from utils.logger import get_logger

logger = get_logger()

def sync_codebase(target_repo_path: str, repo_name: str):
    # Initialize workspace structure
    librarian = Librarian(workspace_root=".", repo_name=repo_name)
    
    # 1. Scan directory for changes
    manifest = librarian.scan_repository(target_repo_path)
    
    # 2. Initialize our parser mapping into the active graph object
    parser = UniversalParser(librarian.graph)
    # parser = CodebaseASTParser(librarian.graph)
    
    parsed_count = 0
    for rel_path, file_meta in manifest.items():
        if file_meta["status"] == "modified":
            logger.info(f"Parsing modified file: {rel_path}")
            parser.parse_file(
                absolute_path=file_meta["absolute_path"],
                relative_path=rel_path,
                file_hash=file_meta["hash"]
            )
            parsed_count += 1
            
    # 3. Serialize changes to disk
    if parsed_count > 0:
        librarian.save_graph()
        logger.info(f"Phase 1 complete. Graph updated. Re-indexed {parsed_count} files.")
    else:
        logger.info("No files modified. Skeleton graph is up to date.")

if __name__ == "__main__":
    # Point this to a test folder with a couple of python scripts to try it out!
    sync_codebase(target_repo_path=settings.TARGET_REPO_PATH, repo_name=settings.REPO_NAME)