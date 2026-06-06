from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import text

from common.config import settings
from common.db.mysql import AsyncSessionLocal, get_mysql_session


async def get_current_user(
    request: Request,
    db: Annotated = Depends(get_mysql_session),
) -> dict:
    """Decode the JWT bearer token and return the user row from MySQL."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from None

    user_id = payload.get("sub")
    username = payload.get("username")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token payload missing user id")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, username, email, role FROM users WHERE id = :id LIMIT 1"),
            {"id": int(user_id)},
        )
        row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "email": str(row["email"]),
        "role": str(row["role"]),
    }


async def get_current_user_id(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> int:
    """Resolve the authenticated user_id for tenant isolation."""
    return current_user["id"]


CurrentUser = Annotated[dict, Depends(get_current_user)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]
