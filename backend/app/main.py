from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from sqlalchemy import text
import uvicorn

from app.routers.auth import router as auth_router
from app.routers.papers import router as papers_router, folders_router
from app.routers.ingest import router as ingest_router
from app.routers.chat import router as chat_router
from app.routers.advanced import router as advanced_router
from app.routers.observability import router as observability_router
from common.config import settings
from common.db.mysql import AsyncSessionLocal
from common.logging import logger

app = FastAPI(
    title="ScholarMind API",
    description="ScholarMind (文渊) - 跨语言学术文献智能调研系统后端 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_user_id(request: Request) -> int | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    user_id = payload.get("sub")
    try:
        return int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    response = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        ip = request.client.host if request.client else None
        user_id = _extract_user_id(request)
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO access_logs (user_id, method, path, status_code, ip, latency_ms)
                        VALUES (:user_id, :method, :path, :status_code, :ip, :latency_ms)
                        """
                    ),
                    {
                        "user_id": user_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "ip": ip,
                        "latency_ms": latency_ms,
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - access logging must never block requests.
            logger.warning(f"[access-log] write failed: {exc}")


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
        "env": settings.APP_ENV,
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.APP_PORT, reload=True)
