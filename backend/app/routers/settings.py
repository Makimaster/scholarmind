"""User-scoped settings API: read/write RAG toggle overrides via Redis."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserId
from common.clients.redis import get_redis
from common.config import RAG_BOOL_KEYS, rag_flag

router = APIRouter(prefix="/settings", tags=["settings"])

SETTINGS_REDIS_KEY = "user_rag_settings:{user_id}"
SETTINGS_TTL_SECONDS = 86400 * 7  # 7 days


@router.get("", summary="获取用户 RAG 开关设置", description="返回当前用户的 8 个 RAG 优化开关值。")
async def get_user_rag_settings(user_id: CurrentUserId = None):  # type: ignore[valid-type]
    redis = get_redis()
    raw = redis.get(SETTINGS_REDIS_KEY.format(user_id=user_id))
    stored: dict[str, bool] = {}
    if raw:
        import json

        stored = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        stored = {k: bool(v) for k, v in stored.items() if k in RAG_BOOL_KEYS}
    # Merge with defaults so the UI always sees all keys.
    result: dict[str, bool] = {}
    for key in sorted(RAG_BOOL_KEYS):
        result[key] = stored.get(key, rag_flag(key))
    return {"settings": result}


@router.put("", summary="保存用户 RAG 开关设置", description="保存当前用户的 RAG 优化开关值，下次检索即时生效。")
async def set_user_rag_settings(overrides: dict[str, bool], user_id: CurrentUserId = None):  # type: ignore[valid-type]
    if not overrides:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No settings provided")
    cleaned = {}
    for key, value in overrides.items():
        if key in RAG_BOOL_KEYS:
            cleaned[key] = bool(value)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid RAG keys provided")
    redis = get_redis()
    import json

    redis.setex(SETTINGS_REDIS_KEY.format(user_id=user_id), SETTINGS_TTL_SECONDS, json.dumps(cleaned))
    return {"status": "saved", "settings": cleaned}
