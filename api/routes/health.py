"""
Check if the FastAPI backend is up or not.
"""

from fastapi import APIRouter

from config import settings

router = APIRouter(
    tags=["Health"]
)


@router.get("/health")
async def health_check():
    return {
        "status": "online",
        "model": settings.app_name
    }