import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from config import settings
from api.middleware import setup_middlewares
from utils.exception_handler import setup_exception_handlers
from utils.logger import get_logger, hook_uvicorn_logging

from api.routes import health, ingest, query

logger = get_logger()

# Define the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):

    # Intercept Uvicorn's active terminal streams and apply localgraph logging properties
    hook_uvicorn_logging()
    
    # --- Startup Logic ---
    logger.info("LocalGraph API is starting up on port 8000...")
    
    yield # The application runs while yielded
    
    # --- Shutdown Logic ---
    logger.info("LocalGraph API is shutting down safely...")

def create_app() -> FastAPI:
    app = FastAPI(
        title="LocalGraph API",
        description="Local Code Knowledge Graph powered by Semantic Kernel and Gemma 4",
        version="1.0.0",
        docs_url="/docs",    
        redoc_url="/redoc",
        lifespan=lifespan    # Attach the lifespan handler here
    )

    # 1. Initialize Middlewares (CORS)
    setup_middlewares(app)

    # 2. Initialize Exception Handlers
    setup_exception_handlers(app)

    # 3. Mount API Routers
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(query.router)

    return app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
# --------------------------------------------------------------------------
# import uvicorn
# from fastapi import FastAPI, BackgroundTasks, HTTPException
# from pydantic import BaseModel

# from config import settings
# from core.librarian import Librarian
# from intelligence_layer.analyst import GraphAnalyst

# app = FastAPI(
#     title="LocalGraph API",
#     description="Local Code Knowledge Graph powered by Semantic Kernel and Gemma 4",
#     version="1.0.0"
# )

# # --- Request Models ---
# class IngestRequest(BaseModel):
#     repo_name: str
#     target_path: str

# # --- Background Tasks ---
# async def run_ingestion_pipeline(repo_name: str, target_path: str):
#     print(f"--- Starting Background Ingestion for {repo_name} ---")
#     try:
#         # Phase 1: Static AST Parsing
#         librarian = Librarian(workspace_root=".", repo_name=repo_name)
#         manifest = librarian.scan_repository(target_path)
        
#         from core.ast_parser import CodebaseASTParser
#         parser = CodebaseASTParser(librarian.graph)
        
#         modified_count = 0
#         for rel_path, file_meta in manifest.items():
#             if file_meta["status"] == "modified":
#                 parser.parse_file(file_meta["absolute_path"], rel_path, file_meta["hash"])
#                 modified_count += 1
                
#         if modified_count > 0:
#             librarian.save_graph()
            
#         # Phase 2: LLM Semantic Analysis
#         analyst = GraphAnalyst(librarian=librarian, target_repo_path=target_path)
#         await analyst.analyze_and_update()
        
#         print(f"--- Completed Background Ingestion for {repo_name} ---")
        
#     except Exception as e:
#         print(f"Ingestion failed for {repo_name}: {e}")

# # --- API Routes ---
# @app.get("/health")
# async def health_check():
#     return {"status": "online", "model": settings.app_name}

# @app.post("/api/v1/ingest", status_code=202)
# async def trigger_ingestion(request: IngestRequest, background_tasks: BackgroundTasks):
#     """
#     Triggers the static parsing and LLM analysis pipeline asynchronously.
#     """
#     background_tasks.add_task(
#         run_ingestion_pipeline, 
#         request.repo_name, 
#         request.target_path
#     )
#     return {
#         "message": "Ingestion started in the background.",
#         "repo_name": request.repo_name,
#         "target_path": request.target_path
#     }

# if __name__ == "__main__":
#     # Run via: uv run python main.py
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    
# # -------------------------------------------------------------------------------------------------
# # from fastapi import FastAPI

# # from api.routes import ingest, health
# # from api.middleware import setup_middleware

# # app = FastAPI(
# #     title="LocalGraph API",
# #     description="Local Code Knowledge Graph powered by Semantic Kernel and Gemma 4",
# #     version="1.0.0"
# # )

# # # Register middleware
# # setup_middleware(app)

# # # Register routers
# # app.include_router(health.router)
# # app.include_router(ingest.router)


# # if __name__ == "__main__":
# #     import uvicorn

# #     uvicorn.run(
# #         "main:app",
# #         host="0.0.0.0",
# #         port=8000,
# #         reload=True
# #     )