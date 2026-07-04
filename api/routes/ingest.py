"""
Defines FastAPI routes for repository ingestion, background processing job polling,
topography generation via Leiden community clustering, and graph serialization for UI maps.
"""

import os
import uuid
import re
import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Any, Dict, List, Set
from pathlib import Path
import networkx as nx
import textwrap
import igraph as ig
import leidenalg

from core.librarian import Librarian
from core.universal_parser import UniversalParser
from core.vector_operations import HybridVectorStore
from models.request import IngestRequest, JobStatusResponse
from intelligence_layer.analyst import GraphAnalyst
from utils.helper import validate_ingestion_path, log_ingestion_stats
from utils.global_cache import load_graph_cached
from utils.constants import SecurityConstraints
from utils.helper import get_ignore_spec
from utils.logger import get_logger
from utils.constants import NodeTypes


logger = get_logger()
router = APIRouter(prefix="/api/v1/ingest", tags=["Ingestion"])

# --- In-Memory Job Queue ---
# Stores the status of background ingestion tasks
JOB_STORE: Dict[str, Dict[str, Any]] = {}


def assign_communities(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """
    Computes modular hierarchical communities using the Leiden algorithm
    and updates the graph metadata structure.
    """
    # Convert networkx → igraph
    undirected_g = G.to_undirected()
    ig_graph = ig.Graph.from_networkx(undirected_g)
    
    # 1. Macro partition
    partition_macro = leidenalg.find_partition(
        ig_graph, 
        leidenalg.ModularityVertexPartition
    )
    
    # Write macro community back
    macro_membership = {}
    for vertex in ig_graph.vs:
        nx_node_id = vertex["_nx_name"]
        comp_id = partition_macro.membership[vertex.index]
        macro_membership[nx_node_id] = comp_id
        G.nodes[nx_node_id]["community_macro"] = comp_id
        G.nodes[nx_node_id]["community"] = comp_id  # Keep fallback
        
    # 2. Micro sub-clustering
    macro_groups = {}
    for node_id, comp_id in macro_membership.items():
        macro_groups.setdefault(comp_id, []).append(node_id)
        
    for macro_id, node_list in macro_groups.items():
        if len(node_list) > 4:
            try:
                subgraph = undirected_g.subgraph(node_list)
                ig_sub = ig.Graph.from_networkx(subgraph)
                partition_micro = leidenalg.find_partition(
                    ig_sub,
                    leidenalg.ModularityVertexPartition
                )
                for vertex in ig_sub.vs:
                    nx_node_id = vertex["_nx_name"]
                    micro_id = partition_micro.membership[vertex.index]
                    G.nodes[nx_node_id]["community_micro"] = f"{macro_id}_{micro_id}"
            except Exception:
                for nx_node_id in node_list:
                    G.nodes[nx_node_id]["community_micro"] = f"{macro_id}_0"
        else:
            for nx_node_id in node_list:
                G.nodes[nx_node_id]["community_micro"] = f"{macro_id}_0"
                
    return G


def _gather_valid_files(target_dir: Path, ignore_spec) -> List[Path]:
    """Helper to traverse the target directory and collect all files not matched by the ignore spec."""
    valid_files = []
    for file_path in target_dir.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = str(file_path.relative_to(target_dir))
        if ignore_spec.match_file(relative_path):
            continue

        valid_files.append(file_path)

        if len(valid_files) > SecurityConstraints.MAX_FILES:
            raise ValueError(
                f"Repository exceeds maximum allowed file count ({SecurityConstraints.MAX_FILES})"
            )
    return valid_files


def _execute_ast_parsing(librarian: Librarian, target_path: str, valid_files: List[Path]) -> Set[str]:
    """Helper to execute the static AST parsing of files in a background worker thread."""
    manifest = librarian.scan_repository(target_path, valid_files=valid_files)
    parser = UniversalParser(librarian.graph)
    modified_files = set()
    
    for rel_path, file_meta in manifest.items():
        if file_meta["status"] == "modified":
            modified_files.add(rel_path)
            parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
            
    # Resolve static import and call linkages across all parsed files
    parser.resolve_all_calls()
            
    # Prune external library calls from the graph
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
    
    return modified_files


async def _execute_llm_analysis(
    req: IngestRequest, 
    librarian: Librarian, 
    target_path: str, 
    modified_files: Set[str], 
    job_id: str, 
    update_ui_progress
) -> None:
    """Helper to trigger the LLM Semantic Analysis (Phase 2) on code files."""
    if req.run_llm:
        update_progress(current=50, total=100, status_message="Running Deep LLM Analysis....", job_id=job_id)
        analyst = GraphAnalyst(
            librarian=librarian, 
            target_repo_path=target_path,
            modified_files=modified_files
        )
        await analyst.analyze_and_update(progress_callback=update_ui_progress)
    else:
        update_progress(current=80, total=100, status_message="Skipping LLM Ingestion...", job_id=job_id)


async def _calculate_topography(librarian: Librarian, update_ui_progress) -> None:
    """Helper to run the Leiden community detection algorithms to cluster graph topology."""
    logger.info("Assigning Leiden communities for visualization...")
    update_ui_progress(current=85, total=100, status_message="Calculating Graph Topography...")
    try:
        librarian.graph = await asyncio.to_thread(assign_communities, librarian.graph)
        await asyncio.to_thread(librarian.save_graph)
        logger.info("Community assignment complete.")
    except Exception as e:
        logger.warning(f"Community clustering failed, continuing without it: {e}")


async def _build_vector_indexes(librarian: Librarian, repo_name: str, update_ui_progress) -> None:
    """Helper to compile and build the FAISS/BM25 vector indexes."""
    logger.info("Building Hybrid FAISS/BM25 Indexes...")
    update_ui_progress(current=95, total=100, status_message="Building FAISS Vector Indexes...")
    
    nodes_data = []
    for node_id, data in librarian.graph.nodes(data=True):
        summary = data.get("summary", "")
        if summary and summary not in ["No summary available.", "pending"]:
            nodes_data.append({
                "node_id": str(node_id), 
                "summary": summary,
                "api_calls": data.get("api_calls", "")
            })
            
    if nodes_data:
        vector_store = HybridVectorStore(repo_name)
        await asyncio.to_thread(vector_store.build_indexes, nodes_data)
        logger.info("Hybrid indexing complete.")
    else:
        logger.warning("No valid summaries found to index.")


async def run_ingestion_pipeline(req: IngestRequest, job_id: str, repo_name: str, target_path: str):
    """The background worker that orchestrates file parsing, LLM analysis, community detection, and vector indexing."""
    JOB_STORE[job_id] = {"status": "processing", "details": {}}
    logger.info(f"Job {job_id} started processing for repo: {repo_name}")

    target_dir = Path(target_path)
    ignore_spec = get_ignore_spec(target_dir)
    
    import time
    t_start = time.perf_counter()
    
    try:
        # 1. Gather all files in scope
        valid_files = _gather_valid_files(target_dir, ignore_spec)
        
        # 2. Phase 1: Static AST Parsing (Graph extraction)
        t_ast_start = time.perf_counter()
        librarian = Librarian(workspace_root=".", repo_name=repo_name)
        modified_files = await asyncio.to_thread(_execute_ast_parsing, librarian, target_path, valid_files)
        duration_ast = time.perf_counter() - t_ast_start
        
        # --- UI CONNECTION: The Streamlit Progress Callback ---
        def update_ui_progress(current: int, total: int, status_message: str):
            JOB_STORE[job_id]["details"] = {
                "current": current,
                "total": total,
                "progress_percent": int((current / total) * 100) if total > 0 else 0,
                "current_file": status_message
            }
            
        # 3. Phase 2: LLM semantic parsing (LLM)
        t_llm_start = time.perf_counter()
        await _execute_llm_analysis(req, librarian, target_path, modified_files, job_id, update_ui_progress)
        duration_llm = time.perf_counter() - t_llm_start
        
        # 4. Phase 3 & 4: Everything else (Community detection + Vector indexing)
        t_else_start = time.perf_counter()
        await _calculate_topography(librarian, update_ui_progress)
        await _build_vector_indexes(librarian, repo_name, update_ui_progress)
        duration_else = (time.perf_counter() - t_else_start) + (t_ast_start - t_start)
        
        # Log stats directly to standard application logs
        log_ingestion_stats(repo_name, duration_ast, duration_llm, duration_else)
        
        # Ingestion Success status
        JOB_STORE[job_id] = {
            "status": "completed",
            "message": "Graph enriched and saved successfully.",
            "details": {"files_modified": len(modified_files), "progress_percent": 100}
        }
        logger.info(f"Job {job_id} completed successfully.")
        
    except Exception as e:
        error_msg = str(e)
        JOB_STORE[job_id] = {
            "status": "failed",
            "message": f"Pipeline failed: {error_msg}",
            "details": {"error": error_msg}
        }
        logger.error(f"Job {job_id} failed: {error_msg}", exc_info=True)
        raise


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
    show_configs: bool = False,
    hierarchy_level: str = "macro"
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
            
            # --- Set absolute defaults BEFORE your if/elif blocks ---
            font_size = 12
            font_color = "#E2E8F0"
            node_color = "#4E79A7"
            node_shape = "dot"
            node_size = 15
            
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
                
            # Create rich HTML tooltip text
            type_display = node_type.capitalize()
            file_path = data.get("file_path", "")
            
            tooltip_html = f"<div style='font-weight: bold; font-size: 13px; color: #fff; margin-bottom: 4px;'>{label}</div>"
            tooltip_html += f"<div style='font-size: 11px; color: #a0aec0; margin-bottom: 6px;'>Type: {type_display}"
            if file_path:
                tooltip_html += f" | File: {file_path}"
            tooltip_html += "</div>"
            
            tooltip_html += "<hr style='border: 0; border-top: 1px solid #4A5568; margin: 6px 0;'>"
            
            if is_pending:
                tooltip_html += "<div style='font-style: italic; color: #BAB0AC;'>⏳ LLM analysis pending for this component...</div>"
            else:
                # Limit summary width gracefully in HTML
                tooltip_html += f"<div style='line-height: 1.4; color: #cbd5e0; font-size: 12px;'>{summary}</div>"
                
            wrapped_title = tooltip_html
            
            # --- USE ALGORITHMIC LEIDEN COMMUNITIES ---
            if hierarchy_level == "micro":
                community_id = data.get("community_micro", data.get("community_macro", file_group))
            else:
                community_id = data.get("community_macro", data.get("community", file_group))
            
            nodes.append({
                "id": str(node_id),
                "label": label,
                "title": wrapped_title,
                "summary": summary,
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
            # --- Only add the edge if BOTH nodes are visible! ---
            if str(source) in valid_node_ids and str(target) in valid_node_ids:
                relation = data.get("relation", "uses")
                confidence = data.get("confidence", "INFERRED")
                
                # Determine display label & tooltip
                # Categorised as: uses [inferred], calls [extracted], method [extracted], contains [extracted], infers [extracted]
                if relation == "contains":
                    label_desc = "contains [extracted]"
                    width = 1.0
                    dashes = [4, 4]  # dashed
                    color = "#718096" # grey
                elif relation == "defines":
                    label_desc = "method [extracted]"
                    width = 1.0
                    dashes = False   # solid
                    color = "#4A5568" # darker grey
                elif relation == "calls":
                    is_inferred = (confidence == "INFERRED")
                    label_desc = f"calls [{'inferred' if is_inferred else 'extracted'}]"
                    width = 2.0
                    dashes = [6, 4] if is_inferred else False
                    color = "#3182ce" # blue
                elif relation == "depends_on":
                    label_desc = "uses [inferred]" if confidence == "INFERRED" else "depends_on [extracted]"
                    width = 3.0
                    dashes = False
                    color = "#dd6b20" # orange/gold
                elif relation == "instantiates":
                    label_desc = "uses [inferred]"
                    width = 1.5
                    dashes = [5, 5]
                    color = "#38a169" # green
                elif relation == "inherits":
                    label_desc = "infers [extracted]" if confidence == "EXTRACTED" else "inherits [extracted]"
                    width = 2.0
                    dashes = False
                    color = "#805ad5" # purple
                else:
                    label_desc = f"{relation} [{confidence.lower()}]"
                    width = 1.5
                    dashes = False
                    color = "#a0aec0" # muted grey
                    
                edges.append({
                    "from": str(source),
                    "to": str(target),
                    "title": label_desc,  # Hover tooltip
                    "label": "",          # Keep label blank so graph is clean, but title is shown on hover!
                    "width": width,
                    "color": {"color": color, "highlight": color, "hover": color},
                    "dashes": dashes,
                    "arrows": {"to": {"enabled": True, "scaleFactor": 0.8}} if relation not in ["contains", "defines"] else {"to": {"enabled": False}}
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