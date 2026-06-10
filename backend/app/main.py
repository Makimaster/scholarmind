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
from app.routers.settings import router as settings_router
from common.config import RAG_BOOL_KEYS, set_rag_overrides, settings
from common.db.mysql import AsyncSessionLocal
from common.logging import logger
import json as _json

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
async def user_rag_settings_middleware(request: Request, call_next):
    """Load per-user RAG toggle overrides from Redis and inject into contextvar for the request."""
    user_id = _extract_user_id(request)
    if user_id is not None:
        from common.clients.redis import get_redis

        try:
            redis = get_redis()
            raw = redis.get(f"user_rag_settings:{user_id}")
            if raw:
                overrides = _json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                overrides = {k: bool(v) for k, v in overrides.items() if k in RAG_BOOL_KEYS}
                set_rag_overrides(overrides)
        except Exception:  # noqa: BLE001 — must not block requests
            pass
    try:
        return await call_next(request)
    finally:
        set_rag_overrides(None)  # clear contextvar for next request


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
app.include_router(settings_router, prefix="/api")


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
