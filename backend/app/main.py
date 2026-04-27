from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analyze import router as analyze_router
from .config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
