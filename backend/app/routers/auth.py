from __future__ import annotations

from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, CurrentUserId
from app.schemas.auth import Token, UserLogin, UserMe, UserRegister
from common.config import settings
from common.db.mysql import AsyncSessionLocal

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _create_jwt(user: dict) -> str:
    now = datetime.utcnow()
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@router.post(
    "/register",
    response_model=UserMe,
    status_code=status.HTTP_201_CREATED,
    summary="用户注册",
    description="注册新账号，返回用户信息。用户名/邮箱唯一，密码 bcrypt 加密存储。",
)
async def register(user_data: UserRegister):
    password_hash = _hash_password(user_data.password)
    async with AsyncSessionLocal() as session, session.begin():
        result = await session.execute(
            text(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (:username, :email, :password_hash, 'user')
                """
            ),
            {"username": user_data.username, "email": user_data.email, "password_hash": password_hash},
        )
        await session.commit()
        user_id = int(result.lastrowid)
    return UserMe(id=user_id, username=user_data.username, email=user_data.email, role="user", is_active=True)


@router.post(
    "/login",
    response_model=Token,
    summary="用户登录",
    description="用户名+密码登录，返回 JWT access_token（有效期 7 天）。后续所有业务接口需在 Header 带 `Authorization: Bearer <token>`。",
)
async def login(credentials: UserLogin):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, username, email, role, password_hash FROM users WHERE username = :username LIMIT 1"),
            {"username": credentials.username},
        )
        row = result.mappings().first()

    if row is None or not _verify_password(credentials.password, str(row["password_hash"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = _create_jwt(dict(row))
    return Token(access_token=token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserMe,
    summary="当前登录用户信息",
    description="返回当前 JWT 对应的用户信息，可用于前端初始化用户状态。",
)
async def get_me(current_user: CurrentUser):
    return UserMe(
        id=current_user["id"],
        username=current_user["username"],
        email=current_user["email"],
        role=current_user["role"],
        is_active=True,
    )
