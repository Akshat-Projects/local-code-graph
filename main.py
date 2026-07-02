"""
Serves as the main entry point to launch the FastAPI backend server for LocalGraph AI,
handling middleware setup, exception handling, custom uvicorn logging hooks, and API routing.
"""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
import multiprocessing.resource_tracker as _rt
import traceback as _tb
from tqdm.std import TqdmDefaultWriteLock as _TqdmLock

from config import settings
from api.middleware import setup_middlewares
from utils.exception_handler import setup_exception_handlers
from utils.logger import get_logger, hook_uvicorn_logging

from api.routes import health, ingest, query


logger = get_logger()


_TqdmLock()

_orig_register = _rt.register

# Tracing root cause of leaked Semaphore items
def _traced_register(name, rtype):
    logger.info(f"\n[SEM-TRACK] register rtype={rtype} name={name}")
    _tb.print_stack(limit=12)
    return _orig_register(name, rtype)

_rt.register = _traced_register

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
