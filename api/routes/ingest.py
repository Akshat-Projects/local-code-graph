from fastapi import APIRouter, BackgroundTasks
from models.request import IngestRequest

from core.librarian import Librarian
from core.ast_parser import CodebaseASTParser
from intelligence_layer.analyst import GraphAnalyst
from utils.logger import get_logger


logger = get_logger()
router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])


async def run_ingestion_pipeline(repo_name: str, target_path: str):
    """Background task handling static AST parsing and LLM semantic extraction."""
    logger.info(f"Starting Background Ingestion for repo: {repo_name}")
    try:
        # Phase 1: Static AST Parsing
        librarian = Librarian(workspace_root=".", repo_name=repo_name)
        manifest = librarian.scan_repository(target_path)
        
        parser = CodebaseASTParser(librarian.graph)
        
        modified_count = 0
        for rel_path, file_meta in manifest.items():
            if file_meta["status"] == "modified":
                parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
                modified_count += 1
                
        if modified_count > 0:
            librarian.save_graph()
            logger.info(f"Phase 1 complete. Parsed {modified_count} modified files.")
            
        # Phase 2: LLM Semantic Analysis
        analyst = GraphAnalyst(librarian=librarian, target_repo_path=target_path)
        await analyst.analyze_and_update()
        
        logger.info(f"Completed Background Ingestion successfully for: {repo_name}")
        
    except Exception as e:
        logger.error(f"Ingestion failed for {repo_name}: {e}", exc_info=True)

@router.post("", status_code=202)
async def trigger_ingestion(request: IngestRequest, background_tasks: BackgroundTasks):
    """
    Triggers the code graph parsing and LLM semantic mapping asynchronously.
    """
    background_tasks.add_task(
        run_ingestion_pipeline, 
        request.repo_name, 
        request.target_path
    )
    return {
        "message": "Ingestion started in the background.",
        "repo_name": request.repo_name,
        "target_path": request.target_path
    }
    