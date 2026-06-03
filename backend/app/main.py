from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from common.config import settings
from common.logging import logger

from app.routers.auth import router as auth_router
from app.routers.papers import router as papers_router, folders_router
from app.routers.ingest import router as ingest_router
from app.routers.chat import router as chat_router
from app.routers.advanced import router as advanced_router
from app.routers.observability import router as observability_router

app = FastAPI(
    title="ScholarMind API",
    description="ScholarMind (文渊) - 跨语言学术文献智能调研系统后端 API",
    version="1.0.0"
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers under /api prefix
app.include_router(auth_router, prefix="/api")
app.include_router(papers_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(advanced_router, prefix="/api")
app.include_router(observability_router, prefix="/api")

@app.get("/health")
async def health_check():
    logger.info("Health check endpoint hit")
    return {
        "status": "healthy",
        "service": "scholarmind",
        "env": settings.APP_ENV
    }

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.APP_PORT, reload=True)
