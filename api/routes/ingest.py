import uuid
import re
from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.request import IngestRequest, JobStatusResponse
from typing import Any, Dict
from pathlib import Path
import networkx as nx
import textwrap

from core.librarian import Librarian
from core.ast_parser import CodebaseASTParser
from intelligence_layer.analyst import GraphAnalyst
from utils.helper import validate_ingestion_path
from utils.constants import SecurityConstraints
from utils.helper import get_ignore_spec
from utils.logger import get_logger



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
    
    try:
        # Phase 1: Static AST Parsing
        librarian = Librarian(workspace_root=".", repo_name=repo_name)
        
        # --- CONNECTION: Pass the filtered list instead of just the path ---
        manifest = librarian.scan_repository(target_path, valid_files=valid_files)
        
        parser = CodebaseASTParser(librarian.graph)
        # modified_count = 0
        modified_files = set()
        for rel_path, file_meta in manifest.items():
            if file_meta["status"] == "modified":
                modified_files.add(rel_path)
                parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
                
                # modified_count += 1
                
        # if modified_count > 0:
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
        analyst = GraphAnalyst(
            librarian=librarian, 
            target_repo_path=target_path,
            modified_files=modified_files)
        # Pass the callback so the backend can talk to the Streamlit UI!
        await analyst.analyze_and_update(progress_callback=update_ui_progress)
        
        # Mark Job as Successful
        JOB_STORE[job_id] = {
            "status": "completed",
            "message": "Graph enriched and saved successfully.",
            "details": {"files_modified": len(modified_files), "progress_percent": 100}
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
    

@router.get("/visualize/{repo_name}")
async def get_graph_visualization(repo_name: str):
    """Returns the graph data formatted for vis.js / streamlit-agraph."""
    
    temp_librarian = Librarian(workspace_root=".", repo_name=repo_name)
    graph_path = Path(temp_librarian.graph_path)
    
    if not graph_path.exists():
        logger.error(f"❌ VISUALIZER ERROR: Graph file not found at {graph_path.absolute()}")
        raise HTTPException(status_code=404, detail="Graph not found. Ingest the repo first.")
        
    try:
        G = nx.read_graphml(graph_path, node_type=str) 
        
        nodes = []
        edges = []
        
        # Collect unique file groups to assign colors using Tableau 10 palette
        unique_groups = sorted(list(set(str(nid).split("::")[0] for nid in G.nodes())))
        tableau10 = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]
        group_colors = {group: tableau10[i % len(tableau10)] for i, group in enumerate(unique_groups)}
        
        # Format Nodes
        for node_id, data in G.nodes(data=True):
            node_type = data.get("type", "unknown")
            
            parts = str(node_id).split("::")
            file_group = parts[0] 
            label = parts[-1]
            
            # 1. Color node based on its file group (clustering by module)
            color = group_colors.get(file_group, "#E2E8F0")
            
            # 2. Scale node size dynamically based on degree (hubness) and node type
            degree = G.degree(node_id)
            if node_type == "file":
                size = 32 + min(degree * 2, 20)
                font_size = 11
                font_color = "#E2E8F0"
                shape = "hexagon"
                mass = 6
            elif node_type == "class":
                size = 18 + min(degree * 1.5, 12)
                font_size = 9
                font_color = "#CBD5E0"
                shape = "dot"
                mass = 2
            else: # function/method
                size = 10 + min(degree * 1, 8)
                font_size = 0  # Hide labels of small methods/functions to prevent screen clutter
                font_color = "#A0AEC0"
                shape = "dot"
                mass = 1
            
            # Smart Tooltips
            summary = data.get("summary", "").strip()
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            if not summary or summary == "No summary available.":
                if node_type == "file":
                    raw_title = f"📄 Source File: {label}"
                elif node_type == "class":
                    raw_title = f"📦 Class: {label}"
                else:
                    raw_title = f"⚙️ Function: {label}"
            else:
                raw_title = summary
                
            wrapped_title = textwrap.fill(raw_title, width=60)
            
            nodes.append({
                "id": str(node_id),
                "label": label,       # truncated display label
                "title": wrapped_title,
                "summary": wrapped_title,
                "group": file_group,
                "type": node_type,  
                "shape": shape,
                "color": color,
                "size": size,
                "mass": mass,
                "font": {"size": font_size, "color": font_color},  # hide labels for methods by default
            })
        
        # # Format Nodes
        # for node_id, data in G.nodes(data=True):
        #     node_type = data.get("type", "unknown")
        #     label = str(node_id).split("::")[-1]
            
        #     # 1. Color-code based on entity type
        #     color = "#E2E8F0"
        #     if node_type == "class": color = "#F6AD55"
        #     elif node_type == "function": color = "#68D391"
        #     elif node_type == "file": color = "#63B3ED"
            
        #     # 2. FIX: Smart Tooltips (Titles)
        #     summary = data.get("summary", "").strip()
        #     if not summary or summary == "No summary available.":
        #         if node_type == "file":
        #             raw_title = f"📄 Source File: {label}"
        #         elif node_type == "class":
        #             raw_title = f"📦 Class: {label}"
        #         else:
        #             raw_title = f"⚙️ Function: {label}"
        #     else:
        #         raw_title = summary
                
        #     # Breaks the text into multiple lines every ~60 characters
        #     wrapped_title = textwrap.fill(raw_title, width=60)
            
        #     nodes.append({
        #         "id": str(node_id),
        #         "label": label,
        #         "title": wrapped_title,
        #         "color": color,
        #         "size": 45 if node_type == "file" else 18 if node_type == "class" else 12,
        #         "mass": 8 if node_type == "file" else 1
        #     })
            
        # Format Edges
        for source, target, data in G.edges(data=True):
            relation = data.get("relation", "")
            
            # 3. FIX: Hide visually obvious structural labels to reduce clutter
            # We keep valuable semantic labels like "calls", "inherits", or "instantiates"
            # display_label = "" if relation in ["contains", "defines"] else relation
            display_label = ""
            
            edges.append({
                "source": str(source),
                "target": str(target),
                "label": display_label
            })
            
        return {"nodes": nodes, "edges": edges}
        
    except Exception as e:
        logger.error(f"❌ VISUALIZER ERROR: Failed to parse graphml: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    
    
def update_progress(current: int, total: int, status_message: str, job_id: str):
    JOB_STORE[job_id]["details"] = {
        "current": current,
        "total": total,
        "progress_percent": int((current / total) * 100) if total > 0 else 0,
        "current_file": status_message
    }