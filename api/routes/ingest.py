from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.request import IngestRequest, JobStatusResponse
from typing import Any, Dict

from core.librarian import Librarian
from core.ast_parser import CodebaseASTParser
from intelligence_layer.analyst import GraphAnalyst
from utils.logger import get_logger
import uuid


logger = get_logger()
router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])

# --- In-Memory Job Queue ---
# Stores the status of background ingestion tasks
JOB_STORE: Dict[str, Dict[str, Any]] = {}

async def run_ingestion_pipeline(job_id: str, repo_name: str, target_path: str):
    """The background worker that updates the global JOB_STORE dictionary."""
    JOB_STORE[job_id]["status"] = "processing"
    logger.info(f"Job {job_id} started processing for repo: {repo_name}")
    
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
            
        # Phase 2: LLM Semantic Analysis
        analyst = GraphAnalyst(librarian=librarian, target_repo_path=target_path)
        await analyst.analyze_and_update()
        
        # Mark Job as Successful
        JOB_STORE[job_id] = {
            "status": "completed",
            "message": "Graph enriched and saved successfully.",
            "details": {"files_modified": modified_count}
        }
        logger.info(f"Job {job_id} completed successfully.")
        
    except Exception as e:
        # Mark Job as Failed and capture the exact error!
        error_msg = str(e)
        JOB_STORE[job_id] = {
            "status": "failed",
            "message": f"Pipeline failed: {error_msg}"
        }
        logger.error(f"Job {job_id} failed: {error_msg}", exc_info=True)


@router.post("", status_code=202, response_model=JobStatusResponse)
async def trigger_ingestion(request: IngestRequest, background_tasks: BackgroundTasks):
    """
    Kicks off the ingestion pipeline and immediately returns a Job ID for tracking.
    """
    job_id = str(uuid.uuid4())
    
    # Initialize the job in our tracking dictionary
    JOB_STORE[job_id] = {"status": "pending"}
    
    # Fire off the worker
    background_tasks.add_task(
        run_ingestion_pipeline, 
        job_id, 
        request.repo_name, 
        request.target_path
    )
    
    return JobStatusResponse(
        job_id=job_id,
        status="pending",
        message="Ingestion queued in the background."
    )

@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Allows the client to poll the status of an ongoing ingestion job.
    """
    if job_id not in JOB_STORE:
        raise HTTPException(status_code=404, detail="Job ID not found.")
        
    job_data = JOB_STORE[job_id]
    
    return JobStatusResponse(
        job_id=job_id,
        status=job_data["status"],
        message=job_data.get("message"),
        details=job_data.get("details")
    )
    
# async def run_ingestion_pipeline(repo_name: str, target_path: str):
#     """Background task handling static AST parsing and LLM semantic extraction."""
#     logger.info(f"Starting Background Ingestion for repo: {repo_name}")
#     try:
#         # Phase 1: Static AST Parsing
#         librarian = Librarian(workspace_root=".", repo_name=repo_name)
#         manifest = librarian.scan_repository(target_path)
        
#         parser = CodebaseASTParser(librarian.graph)
        
#         modified_count = 0
#         for rel_path, file_meta in manifest.items():
#             if file_meta["status"] == "modified":
#                 parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
#                 modified_count += 1
                
#         if modified_count > 0:
#             librarian.save_graph()
#             logger.info(f"Phase 1 complete. Parsed {modified_count} modified files.")
            
#         # Phase 2: LLM Semantic Analysis
#         analyst = GraphAnalyst(librarian=librarian, target_repo_path=target_path)
#         await analyst.analyze_and_update()
        
#         logger.info(f"Completed Background Ingestion successfully for: {repo_name}")
        
#     except Exception as e:
#         logger.error(f"Ingestion failed for {repo_name}: {e}", exc_info=True)

    
# @router.post("", status_code=200)
# async def trigger_ingestion(request: IngestRequest):
#     """
#     Triggers the code graph parsing and LLM semantic mapping synchronously.
#     """
#     logger.info(f"Starting Ingestion for repo: {request.repo_name}")
#     try:
#         # Phase 1: Static AST Parsing
#         librarian = Librarian(workspace_root=".", repo_name=request.repo_name)
#         manifest = librarian.scan_repository(request.target_path)
        
#         parser = CodebaseASTParser(librarian.graph)
        
#         modified_count = 0
#         for rel_path, file_meta in manifest.items():
#             if file_meta["status"] == "modified":
#                 parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
#                 modified_count += 1
                
#         if modified_count > 0:
#             librarian.save_graph()
#             logger.info(f"Phase 1 complete. Parsed {modified_count} modified files.")
            
#         # Phase 2: LLM Semantic Analysis
#         analyst = GraphAnalyst(librarian=librarian, target_repo_path=request.target_path)
#         await analyst.analyze_and_update()
        
#         logger.info(f"Completed Ingestion successfully for: {request.repo_name}")
        
#         # Return strict 200 OK upon actual completion
#         return {
#             "message": "Ingestion completed successfully.",
#             "repo_name": request.repo_name,
#             "target_path": request.target_path,
#             "files_modified": modified_count
#         }
        
#     except Exception as e:
#         logger.error(f"Ingestion failed for {request.repo_name}: {e}", exc_info=True)
#         # Raise a 500 error so the swagger UI / frontend knows it broke
#         raise HTTPException(status_code=500, detail=f"Ingestion pipeline failed: {str(e)}")