from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models.query_llm import QueryRequest
from intelligence_layer.query_engine import GraphQueryEngine
from utils.logger import get_logger

logger = get_logger()
router = APIRouter(prefix="/api/v1/query", tags=["Querying"])

@router.post("")
async def ask_codebase(request: QueryRequest):
    """
    Submits a natural language question and streams the answer back.
    """
    logger.info(f"Received streaming query for repo: {request.repo_name}")
    try:
        engine = GraphQueryEngine(repo_name=request.repo_name)
        
        # Grab the async generator
        response_generator = engine.answer_question_stream(user_query=request.question)
        
        # Stream the chunks down the HTTP connection as plain text
        return StreamingResponse(response_generator, media_type="text/plain")
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process query: {e}")
        raise HTTPException(status_code=500, detail="Internal inference error.")
    
    
# from fastapi import APIRouter, HTTPException

# from intelligence_layer.query_engine import GraphQueryEngine
# from models.query_llm import QueryRequest, QueryResponse
# from utils.logger import get_logger

# logger = get_logger()
# router = APIRouter(prefix="/api/v1/query", tags=["Querying"])



# @router.post("", response_model=QueryResponse)
# async def ask_codebase(request: QueryRequest):
#     """
#     Submits a natural language question against the ingested codebase graph.
#     """
#     logger.info(f"Received query request for repo: {request.repo_name}")
#     try:
#         engine = GraphQueryEngine(repo_name=request.repo_name)
#         answer = await engine.answer_question(user_query=request.question)
#         return {"answer": answer}
#     except FileNotFoundError as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except Exception as e:
#         logger.error(f"Failed to process query: {e}")
#         raise HTTPException(status_code=500, detail="Internal inference error.")