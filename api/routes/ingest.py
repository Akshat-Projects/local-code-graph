import os
import uuid
import re
import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Any, Dict
from pathlib import Path
import networkx as nx
import textwrap
import igraph as ig
import leidenalg

from core.librarian import Librarian
from core.universal_parser import UniversalParser
from core.vector_operations import HybridVectorStore
from core.ast_parser import CodebaseASTParser
from models.request import IngestRequest, JobStatusResponse
from intelligence_layer.analyst import GraphAnalyst
from utils.helper import validate_ingestion_path
from utils.global_cache import load_graph_cached
from utils.constants import SecurityConstraints
from utils.helper import get_ignore_spec
from utils.logger import get_logger



logger = get_logger()
router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])

# --- In-Memory Job Queue ---
# Stores the status of background ingestion tasks
JOB_STORE: Dict[str, Dict[str, Any]] = {}


def assign_communities(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    # Convert networkx → igraph
    ig_graph = ig.Graph.from_networkx(G.to_undirected())
    partition = leidenalg.find_partition(
        ig_graph, 
        leidenalg.ModularityVertexPartition
    )
    
    # Write community ID back to each node using the deterministic _nx_name
    for vertex in ig_graph.vs:
        nx_node_id = vertex["_nx_name"]
        G.nodes[nx_node_id]["community"] = partition.membership[vertex.index]
        
    return G


async def run_ingestion_pipeline(req: IngestRequest, job_id: str, repo_name: str, target_path: str):
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
        
        # --- CONNECTION: Run Phase 1 entirely in a thread to keep FastAPI responsive ---
        def run_phase_1():
            manifest = librarian.scan_repository(target_path, valid_files=valid_files)
            parser = UniversalParser(librarian.graph)
            modified_files = set()
            for rel_path, file_meta in manifest.items():
                if file_meta["status"] == "modified":
                    modified_files.add(rel_path)
                    parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
                    
            # --- ORPHAN PRUNING ---
            logger.info("Pruning external library calls from the graph...")
            real_names = set()
            for node_id, data in librarian.graph.nodes(data=True):
                if data.get("type") in ["file", "class", "function"]:
                    exact_name = str(node_id).split("::")[-1]
                    real_names.add(exact_name)
                    if data.get("type") == "file":
                        real_names.add(exact_name.replace(".py", ""))

            nodes_to_remove = [
                n for n, d in librarian.graph.nodes(data=True) 
                if str(n).startswith("fuzzy::") and str(n).replace("fuzzy::", "") not in real_names
            ]
            for n in nodes_to_remove:
                librarian.graph.remove_node(n)
            logger.info(f"Removed {len(nodes_to_remove)} external/unresolved fuzzy calls.")
            librarian.save_graph()
            return manifest, modified_files

        manifest, modified_files = await asyncio.to_thread(run_phase_1)
            
        # --- UI CONNECTION: The Streamlit Progress Callback ---
        def update_ui_progress(current: int, total: int, status_message: str):
            JOB_STORE[job_id]["details"] = {
                "current": current,
                "total": total,
                "progress_percent": int((current / total) * 100) if total > 0 else 0,
                "current_file": status_message
            }
            
        # --- GHOST NODE DETECTOR ---
        missing_nodes = [
            n for n, d in librarian.graph.nodes(data=True) 
            if d.get("type") in ["file", "class", "function"] 
            and (not d.get("summary") or d.get("summary") in ["pending", "No summary available."])
        ]
        if missing_nodes:
            logger.warning(f"👻 FOUND {len(missing_nodes)} GHOST NODES. First 20: {missing_nodes[:20]}")
        
        # Phase 2: LLM Semantic Analysis
        if req.run_llm:
            update_progress(current=50, total=100, status_message="Running Deep LLM Analysis....", job_id=job_id)
            

            analyst = GraphAnalyst(
                librarian=librarian, 
                target_repo_path=target_path,
                modified_files=modified_files)
            # Pass the callback so the backend can talk to the Streamlit UI!
            await analyst.analyze_and_update(progress_callback=update_ui_progress)
        else:
            update_progress(current=80, total=100, status_message="Skipping LLM Ingestion...", job_id=job_id)
            
        logger.info("Assigning Leiden communities for visualization...")
        update_ui_progress(current=85, total=100, status_message="Calculating Graph Topography...")
        
        try:
            librarian.graph = await asyncio.to_thread(assign_communities, librarian.graph)
            await asyncio.to_thread(librarian.save_graph) # Persist the community data to disk
            logger.info("Community assignment complete.")
        except Exception as e:
            logger.warning(f"Community clustering failed, continuing without it: {e}")
        # ==========================================
        # --- POPULATE THE DUAL-INDEX STORE ---
        # ==========================================
        
        logger.info("Building Hybrid FAISS/BM25 Indexes...")
        update_ui_progress(current=95, total=100, status_message="Building FAISS Vector Indexes...")
        
        nodes_data = []
        for node_id, data in librarian.graph.nodes(data=True):
            summary = data.get("summary", "")
            # Only index nodes that actually have valid text
            if summary and summary not in ["No summary available.", "pending"]:
                nodes_data.append({"node_id": str(node_id), "summary": summary})
                
        if nodes_data:
            vector_store = HybridVectorStore(repo_name)
            await asyncio.to_thread(vector_store.build_indexes, nodes_data)
            logger.info("Hybrid indexing complete.")
        else:
            logger.warning("No valid summaries found to index.")     
            
               
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
        request, 
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
async def get_graph_visualization(
    repo_name: str,
    target_path: str | None = None,
    show_configs: bool = False
):
    """Returns the graph data formatted for vis.js / streamlit-agraph."""
    # 1. Get the absolute path to the root of your Python project securely
    project_root = os.getcwd() 
    workspace_root = project_root
    
    if target_path:
        try:
            target_dir = validate_ingestion_path(target_path)
            potential_path = target_dir / ".localgraph" / "storage" / repo_name / "graph.graphml"
            if potential_path.exists():
                workspace_root = str(target_dir)
        except Exception as e:
            logger.warning(f"Failed to validate target_path for visualization: {e}")
            
    temp_librarian = Librarian(workspace_root=workspace_root, repo_name=repo_name)
    graph_path = temp_librarian.graph_path
    
    if not graph_path.exists():
        logger.error(f"❌ VISUALIZER ERROR: Graph file not found at {graph_path.absolute()}")
        raise HTTPException(status_code=404, detail="Graph not found. Ingest the repo first.")
        
    try:
        G = await load_graph_cached(graph_path) 
        
        nodes = []
        edges = []
        valid_node_ids = set()
        
        # Format Nodes
        for node_id, data in G.nodes(data=True):
            node_type = data.get("type", "unknown")
            
            parts = str(node_id).split("::")
            file_group = parts[0] 
            label = parts[-1]
            
            # --- Config Filter Logic ---
            is_config = False
            if node_type == "file" and label.endswith(('.json', '.yml', '.yaml', '.txt', '.toml')):
                is_config = True
            elif node_type in ["library", "infrastructure"]:
                is_config = True
                
            if not show_configs and is_config:
                continue
                
            valid_node_ids.add(str(node_id))
            
            # 1. Scale node size AND MASS dynamically based on degree (hubness)
            degree = G.degree(node_id)
            base_size = 10 + (degree * 1.6)
            size = min(base_size, 40)       
            shape = "dot"
            mass = 1 + (degree * 0.1)
            
            if node_type == "file":
                if label.endswith(('.json', '.yml', '.yaml', '.txt', '.toml')):
                    shape = "square"    # <--- Configs become squares!
                    size = 22
                    font_color = "#F28E2B"
                else:
                    size = 20 + min(degree * 0.8, 13) 
                    font_size = 11 if degree >= 2 else 0
                    font_color = "#E2E8F0"
                    mass = 3 + (degree * 0.1) 
            elif node_type == "class":
                size = 14 + min(degree * 0.8, 7)
                font_size = 9 if degree >= 2 else 0
                font_color = "#CBD5E0"
                mass = 2
            else: 
                size = 10 + min(degree * 0.5, 4)
                font_size = 0  
                font_color = "#A0AEC0"
                mass = 1

            if not label.endswith(('.json', '.yml', '.yaml', '.txt', '.toml')):
                if degree >= 10:
                    font_size = 12
                    font_color = "#ffffff"
                else:
                    font_size = 10
                    font_color = "#ffffff"
            
            # Smart Tooltips
            summary = data.get("summary", "").strip()
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            is_pending = False
            
            if not summary or summary == "No summary available." or summary == "pending":
                is_pending = True
                if node_type == "file":
                    raw_title = f"📄 Source File: {label}"
                elif node_type == "class":
                    raw_title = f"📦 Class: {label}"
                else:
                    raw_title = f"⚙️ Function: {label}"
            else:
                raw_title = summary
                
            wrapped_title = textwrap.fill(raw_title, width=60)
            # --- USE ALGORITHMIC LEIDEN COMMUNITIES ---
            community_id = data.get("community", file_group)
            
            nodes.append({
                "id": str(node_id),
                "label": label,
                "title": wrapped_title,
                "summary": wrapped_title,
                "type": node_type,  
                "shape": shape,
                "size": size,
                "mass": mass,
                "group": str(community_id), 
                "community": str(community_id),               # Needed for the sidebar UI
                "community_name": f"Community {community_id}",# Needed for the sidebar UI
                "_file_type": node_type,                      # Needed for the sidebar UI
                "font": {"size": font_size, "color": font_color},
                "_is_pending": is_pending,
                "color": {"background": "#4E79A7", "border": "#4E79A7"} # Saftey fallback to prevent JS crashes!
            })
            
        # Format Edges
        for source, target, data in G.edges(data=True):
            display_label = ""
            
            # --- Only add the edge if BOTH nodes are visible! ---
            if str(source) in valid_node_ids and str(target) in valid_node_ids:
                edges.append({
                    "from": str(source),
                    "to": str(target),
                    "label": ""
                })
            
            edges.append({
                "from": str(source),   # CRITICAL FIX: Vis.js demands "from", not "source"
                "to": str(target),     # CRITICAL FIX: Vis.js demands "to", not "target"
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