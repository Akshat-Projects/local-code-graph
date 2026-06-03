from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pathlib import Path
import networkx as nx

from core.librarian import Librarian
from models.query_llm import QueryRequest, NodeChatRequest
from utils.helper import validate_ingestion_path
from intelligence_layer.query_engine import GraphQueryEngine
from intelligence_layer.kernel_client import LocalKernelFactory
from utils.logger import get_logger

logger = get_logger()
router = APIRouter(prefix="/api/v1/query", tags=["Querying"])

@router.post("")
async def ask_codebase(request: QueryRequest):
    """
    Submits a natural language question and streams the answer back.
    """
    logger.info(f"Received streaming query for repo: {request.repo_name}")
    target_dir = validate_ingestion_path(
            request.target_path
        )
    try:
        engine = GraphQueryEngine(
            # target_repo_path=request.target_path,
            repo_name=request.repo_name,
            target_repo_path=str(target_dir)
            )
        
        # Grab the async generator
        response_generator = engine.answer_question_stream(
            user_query=request.question, 
            max_tokens=request.max_tokens
            )
        
        # Stream the chunks down the HTTP connection as plain text
        return StreamingResponse(response_generator, media_type="text/plain")
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process query: {e}")
        raise HTTPException(status_code=500, detail="Internal inference error.")
    
    
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
    G = nx.read_graphml(graph_path, node_type=str)
    
    if req.node_id not in G:
        raise HTTPException(status_code=404, detail="Node not found in graph.")
        
    # 2. Extract context for the LLM
    node_data = G.nodes[req.node_id]
    node_type = node_data.get("type", "unknown")
    raw_code = node_data.get("code", "")
    summary = node_data.get("summary", "No summary available.")
    
    logger.info(f"Chat request for {req.node_id}: {req.question}")
    
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