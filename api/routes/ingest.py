from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.request import IngestRequest, JobStatusResponse
from typing import Any, Dict
from utils.helper import get_ignore_spec
from pathlib import Path

from core.librarian import Librarian
from core.ast_parser import CodebaseASTParser
from intelligence_layer.analyst import GraphAnalyst
from utils.helper import validate_ingestion_path
from utils.constants import SecurityConstraints
from utils.logger import get_logger
import uuid


logger = get_logger()
router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])

# --- In-Memory Job Queue ---
# Stores the status of background ingestion tasks
JOB_STORE: Dict[str, Dict[str, Any]] = {}


async def run_ingestion_pipeline(job_id: str, repo_name: str, target_path: str):
    """The background worker that updates the global JOB_STORE dictionary."""
    JOB_STORE[job_id] = {"status": "processing", "details": {}}
    logger.info(f"Job {job_id} started processing for repo: {repo_name}")

    target_dir = Path(target_path)
    ignore_spec = get_ignore_spec(target_dir)
    
    # 1. Build the filtered list
    valid_files = []
    
    for file_path in target_dir.rglob("*"):

        if not file_path.is_file():
            continue

        relative_path = str(
            file_path.relative_to(target_dir)
        )

        if ignore_spec.match_file(relative_path):
            continue

        valid_files.append(file_path)

        if len(valid_files) > SecurityConstraints.MAX_FILES:
            raise ValueError(
                f"Repository exceeds "
                f"maximum allowed file count "
                f"({SecurityConstraints.MAX_FILES})"
            )
    

    for file_path in target_dir.rglob("*"):
        if not file_path.is_file():
            continue
        relative_path = str(file_path.relative_to(target_dir))
        if ignore_spec.match_file(relative_path):
            continue
        valid_files.append(file_path)
    
    try:
        # Phase 1: Static AST Parsing
        librarian = Librarian(workspace_root=".", repo_name=repo_name)
        
        # --- CONNECTION: Pass the filtered list instead of just the path ---
        manifest = librarian.scan_repository(target_path, valid_files=valid_files)
        
        parser = CodebaseASTParser(librarian.graph)
        modified_count = 0
        for rel_path, file_meta in manifest.items():
            if file_meta["status"] == "modified":
                parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
                modified_count += 1
                
        if modified_count > 0:
            librarian.save_graph()
            
        # --- UI CONNECTION: The Streamlit Progress Callback ---
        def update_ui_progress(current: int, total: int, status_message: str):
            JOB_STORE[job_id]["details"] = {
                "current": current,
                "total": total,
                "progress_percent": int((current / total) * 100) if total > 0 else 0,
                "current_file": status_message
            }
            
        # Phase 2: LLM Semantic Analysis
        analyst = GraphAnalyst(librarian=librarian, target_repo_path=target_path)
        # Pass the callback so the backend can talk to the Streamlit UI!
        await analyst.analyze_and_update(progress_callback=update_ui_progress)
        
        # Mark Job as Successful
        JOB_STORE[job_id] = {
            "status": "completed",
            "message": "Graph enriched and saved successfully.",
            "details": {"files_modified": modified_count, "progress_percent": 100}
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
    target_dir = validate_ingestion_path(
        request.target_path
    )
    
    # Initialize the job in our tracking dictionary
    JOB_STORE[job_id] = {"status": "pending"}
    
    # Fire off the worker
    background_tasks.add_task(
        run_ingestion_pipeline, 
        job_id, 
        request.repo_name, 
        str(target_dir)
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
    
    
def update_progress(current: int, total: int, status_message: str, job_id: str):
    JOB_STORE[job_id]["details"] = {
        "current": current,
        "total": total,
        "progress_percent": int((current / total) * 100) if total > 0 else 0,
        "current_file": status_message
    }