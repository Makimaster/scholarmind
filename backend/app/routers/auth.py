from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.auth import UserRegister, UserLogin, Token, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserMe, status_code=status.HTTP_201_CREATED,
             summary="用户注册",
             description="注册新账号，返回用户信息。用户名/邮箱唯一，密码 bcrypt 加密存储。")
async def register(user_data: UserRegister):
    # Mock registration success
    return UserMe(
        id=123,
        username=user_data.username,
        email=user_data.email,
        role="user",
        is_active=True
    )

@router.post("/login", response_model=Token,
             summary="用户登录",
             description="用户名+密码登录，返回 JWT access_token（有效期 7 天）。后续所有业务接口需在 Header 带 `Authorization: Bearer <token>`。")
async def login(credentials: UserLogin):
    # Mock validation and JWT generation
    if credentials.username == "admin" and credentials.password == "admin123":
        return Token(
            access_token="mock-jwt-token-scholarmind-admin",
            token_type="bearer"
        )
    # Default mock token for any login to ease front-end testing
    return Token(
        access_token="mock-jwt-token-scholarmind-guest",
        token_type="bearer"
    )

@router.get("/me", response_model=UserMe,
            summary="当前登录用户信息",
            description="返回当前 JWT 对应的用户信息，可用于前端初始化用户状态。")
async def get_me():
    # Mock current authenticated user retrieval
    return UserMe(
        id=999,
        username="scholar_user",
        email="user@scholarmind.org",
        role="user",
        is_active=True
    )
