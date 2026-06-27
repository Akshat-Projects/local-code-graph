import re
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pathlib import Path
from fastapi.responses import StreamingResponse

from core.librarian import Librarian
from models.query_llm import QueryRequest, NodeChatRequest
from utils.helper import validate_ingestion_path, secure_path_join
from intelligence_layer.query_engine import GraphQueryEngine
from intelligence_layer.kernel_client import LocalKernelFactory
from utils.logger import get_logger
from utils.global_cache import load_graph_cached
from agents.graph import agent_app


logger = get_logger()
router = APIRouter(prefix="/api/v1/query", tags=["Querying"])


@router.post("")
async def ask_codebase(request: QueryRequest):
    """
    Submits a natural language question and streams the LangGraph agent answers back.
    """
    logger.info(f"Received streaming query for repo: {request.repo_name}")
    logger.info(f"Received Chat History Length: {len(request.chat_history)} characters") 
    
    # Validate the directory path
    target_dir = validate_ingestion_path(request.target_path)
    
    # 1. Initialize the starting values on our state whiteboard
    initial_state = {
        "repo_name": request.repo_name,
        "target_repo_path": str(target_dir),
        "user_query": request.question,
        "chat_history": request.chat_history,
        "intent": "",
        "structural_context": [],
        "temporal_context": [],
        "final_response": ""
    }

    # 2. Define an async generator to stream tokens out of LangGraph live
    async def langgraph_streamer():
        seen_nodes = set()  # 🛡️ FIX 1: Tracker to prevent duplicate UI spam
        
        try:
            # 📝 OPEN A DEBUG FILE
            with open("debug_chunks.log", "w", encoding="utf-8") as debug_file:
                debug_file.write("--- NEW GENERATION RUN ---\n")
                async for event in agent_app.astream_events(initial_state, version="v2"):
                    kind = event.get("event")
                    node_name = event.get("metadata", {}).get("langgraph_node", "")

                    # 🌟 1. Broadcast Status (Strictly ONCE per node)
                    if kind == "on_chain_start" and node_name and node_name not in seen_nodes:
                        seen_nodes.add(node_name)
                        
                        if node_name == "router":
                            yield json.dumps({"type": "status", "content": "Supervisor Agent routing query..."}) + "\n"
                        elif node_name == "graph_agent":
                            yield json.dumps({"type": "status", "content": "Architect Agent querying structure..."}) + "\n"
                        elif node_name == "synthesizer":
                            yield json.dumps({"type": "status", "content": "Writer Agent drafting response..."}) + "\n"
                        elif node_name == "conversational":
                            yield json.dumps({"type": "status", "content": "Chat Agent processing small talk..."}) + "\n"

                    # 🌟 2. Broadcast Text AND Hidden Reasoning Thoughts
                    elif kind == "on_chat_model_stream":
                        if node_name in ["synthesizer", "conversational"]:
                            chunk = event["data"].get("chunk")
                            if chunk:
                                # 🧠 FIX 2: Dig out the hidden llama.cpp/DeepSeek reasoning
                                debug_file.write(f"{chunk.dict()}\n")
                                debug_file.flush()
                                reasoning = chunk.additional_kwargs.get("reasoning_content")
                                if reasoning:
                                    yield json.dumps({"type": "thought", "content": reasoning}) + "\n"
                                
                                # 📝 Standard markdown text
                                if chunk.content:
                                    yield json.dumps({"type": "chunk", "content": chunk.content}) + "\n"
                                    
                    elif kind == "on_chain_end" and node_name == "router":
                        output = event.get("data", {}).get("output", {})
                        intent = output.get("intent") if isinstance(output, dict) else None
                        if intent:
                            yield json.dumps({
                                "type": "thought",
                                "content": f"\n\n**Routing decision:** `{intent}`\n\n"
                            }) + "\n"

                    elif kind == "on_chain_end" and node_name == "graph_agent":
                        output = event.get("data", {}).get("output", {})
                        ctx_list = output.get("structural_context", []) if isinstance(output, dict) else []
                        if ctx_list:
                            preview = ctx_list[0][:400]
                            yield json.dumps({
                                "type": "thought",
                                "content": f"\n\n**Retrieved context (preview):**\n```\n{preview}...\n```\n\n"
                            }) + "\n"
                            
                    elif kind == "on_chain_end" and node_name in ["synthesizer", "conversational"]:
                        output = event.get("data", {}).get("output", {})
                        telemetry = output.get("telemetry") if isinstance(output, dict) else None
                        elapsed = output.get("elapsed_seconds") if isinstance(output, dict) else None
                        if telemetry and elapsed is not None:
                            predicted_n = telemetry.get("predicted_n", 0)
                            payload = {
                                **telemetry,
                                "time_taken": round(elapsed, 2),
                                "tps": round(predicted_n / elapsed, 2) if elapsed > 0 else 0,
                            }
                            yield json.dumps({"type": "telemetry", **payload}) + "\n"
                                    
        except Exception as e:
            logger.error(f"LangGraph Streaming Error: {e}")
            # Ensure errors are safely JSON formatted so they don't crash app.py
            yield json.dumps({"type": "error", "content": f"Generation failed midway: {str(e)}"}) + "\n"

    try:
        # 3. Stream the chunks down the HTTP connection seamlessly!
        return StreamingResponse(langgraph_streamer(), media_type="text/plain")
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process query: {e}")
        raise HTTPException(status_code=500, detail="Internal agent execution error.")
# @router.post("")
# async def ask_codebase(request: QueryRequest):
#     """
#     Submits a natural language question and streams the answer back.
#     """
#     logger.info(f"Received streaming query for repo: {request.repo_name}")
#     logger.info(f"Received Chat History Length: {len(request.chat_history)} characters") 
    
#     target_dir = validate_ingestion_path(
#             request.target_path
#         )
#     try:
#         engine = GraphQueryEngine(
#             # target_repo_path=request.target_path,
#             repo_name=request.repo_name,
#             target_repo_path=str(target_dir),
#             )
        
#         # Grab the async generator
#         response_generator = engine.answer_question_stream(
#             user_query=request.question, 
#             max_tokens=request.max_tokens,
#             chat_history=request.chat_history
#             )
        
#         # Stream the chunks down the HTTP connection as plain text
#         return StreamingResponse(response_generator, media_type="text/plain")
        
#     except FileNotFoundError as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except Exception as e:
#         logger.error(f"Failed to process query: {e}")
#         raise HTTPException(status_code=500, detail="Internal inference error.")
    
    
@router.post("/node/{repo_name}")
async def chat_with_node(repo_name: str, req: NodeChatRequest):
    """Answers a question specifically focused on a single graph node."""
    
    # 1. FIX: Use Librarian to resolve the correct path!
    temp_librarian = Librarian(workspace_root=".", repo_name=repo_name)
    graph_path = Path(temp_librarian.graph_path)
    
    if not graph_path.exists():
        logger.error(f"❌ QUERY ERROR: Graph file not found at {graph_path.absolute()}")
        raise HTTPException(status_code=404, detail="Graph not found. Ingest first.")
        
    # Load the graph
    G = await load_graph_cached(graph_path)
    
    if req.node_id not in G:
        raise HTTPException(status_code=404, detail="Node not found in graph.")
        
    # 2. Extract context for the LLM
    node_data = G.nodes[req.node_id]
    node_type = node_data.get("type", "unknown")
    raw_code = "Code not found in memory."
    summary = node_data.get("summary", "No summary available.")
    
    logger.info(f"Chat request for {req.node_id}: {req.question}")
    if req.target_path:
        # Node IDs are usually formatted like "path/to/file.py::ClassName::method" or "path/to/file.py"
        # We split by "::" to get just the file path, or strip the "file::" prefix.
        node_id_str = req.node_id
        if node_id_str.startswith("file::"):
            file_rel_path = node_id_str[6:]
        else:
            file_rel_path = node_id_str.split("::")[0]
        
        try:
            full_file_path = secure_path_join(req.target_path, file_rel_path)
            if full_file_path.exists() and full_file_path.is_file():
                # Read the actual file directly from the hard drive!
                with open(full_file_path, "r", encoding="utf-8") as f:
                    raw_code = f.read()
        except HTTPException as he:
            raise he
        except Exception as e:
            logger.warning(f"Could not read live code for {req.node_id}: {e}")
    # 3. The Real LLM Integration
    prompt = f"""
    You are an expert software architect analyzing a specific codebase component.
    
    Component Name: {req.node_id}
    Component Type: {node_type}
    Component Summary: {summary}
    Relevant Code: {raw_code}
    
    The user has a question specifically about this component:
    "{req.question}"
    
    Provide a clear, concise, and highly technical answer based ONLY on the context provided above.
    """
    kernel = LocalKernelFactory.create_kernel()
    # --- Asynchronous Generator for Streaming ---
    async def generate():
        try:
            async for chunk in kernel.invoke_prompt_stream(prompt):
                # The 'chunk' object is a list of StreamingChatMessageContent
                for message_content in chunk:
                    # Iterate through the items in the message
                    for item in message_content.items:
                        # Check if it has a 'text' attribute
                        if hasattr(item, 'text') and item.text:
                            yield item.text
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"\n\n**Error:** Generation failed midway ({str(e)})"
                
    # Return a raw text stream instead of a JSON dictionary
    return StreamingResponse(generate(), media_type="text/plain")



@router.get("/status/{repo_name}")
async def get_graph_status(repo_name: str):
    """Unified endpoint to calculate graph health and pending summaries."""
    temp_librarian = Librarian(workspace_root=".", repo_name=repo_name)
    graph_path = Path(temp_librarian.graph_path)
    
    if not graph_path.exists():
        return {
            "exists": False,
            "total_nodes": 0,
            "pending_summaries": 0,
            "is_complete": False
        }
        
    try:
        G = await load_graph_cached(graph_path)
        total_nodes = len(G.nodes)
        pending_summaries = 0
        
        for _, data in G.nodes(data=True):
            summary = data.get("summary", "").strip()
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            
            if not summary or summary == "No summary available.":
                pending_summaries += 1
                
        return {
            "exists": True,
            "total_nodes": total_nodes,
            "pending_summaries": pending_summaries,
            "is_complete": pending_summaries == 0
        }
    except Exception as e:
        logger.error(f"Failed to calculate graph status for {repo_name}: {e}")
        return {
            "exists": True,
            "total_nodes": 0,
            "pending_summaries": 0,
            "is_complete": False,
            "error": str(e)
        }