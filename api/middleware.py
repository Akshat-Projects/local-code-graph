from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings

def setup_middlewares(app: FastAPI):
    """
    Configures global middlewares like CORS.
    """
    allow_origins=[
    origin.strip()
    for origin in settings.ALLOWED_ORIGIN.split(",")
    if origin.strip()    ]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,  # Adjust this to specific domains in production
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],  # Allows all HTTP methods (GET, POST, etc.)
        allow_headers=["*"],  # Allows all headers
    )