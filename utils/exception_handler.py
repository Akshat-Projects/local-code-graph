"""
Registers global exception handlers for the FastAPI application, capturing
uncaught runtime errors and formatting them as standard JSON error responses.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from utils.logger import get_logger

logger = get_logger()

def setup_exception_handlers(app):

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request,
        exc: Exception
    ):
        logger.exception(str(exc))

        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal Server Error"
            }
        )