from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def setup_middlewares(app: FastAPI):
    """
    Configures global middlewares like CORS.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust this to specific domains in production
        allow_credentials=True,
        allow_methods=["*"],  # Allows all HTTP methods (GET, POST, etc.)
        allow_headers=["*"],  # Allows all headers
    )
# --------------------------------------------------------------
# import time

# from fastapi import Request
# from fastapi.middleware.cors import CORSMiddleware


# async def logging_middleware(
#     request: Request,
#     call_next
# ):
#     start = time.time()

#     response = await call_next(request)

#     duration = time.time() - start

#     print(
#         f"{request.method} "
#         f"{request.url.path} "
#         f"completed in {duration:.4f}s"
#     )

#     return response


# def setup_middleware(app):

#     # Request logging middleware
#     app.middleware("http")(logging_middleware)

#     # CORS middleware
#     app.add_middleware(
#         CORSMiddleware,
#         allow_origins=["*"],
#         allow_credentials=True,
#         allow_methods=["*"],
#         allow_headers=["*"],
#     )