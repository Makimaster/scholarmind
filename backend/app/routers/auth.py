from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.auth import UserRegister, UserLogin, Token, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserMe, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    # Mock registration success
    return UserMe(
        id=123,
        username=user_data.username,
        email=user_data.email,
        role="user",
        is_active=True
    )

@router.post("/login", response_model=Token)
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

@router.get("/me", response_model=UserMe)
async def get_me():
    # Mock current authenticated user retrieval
    return UserMe(
        id=999,
        username="scholar_user",
        email="user@scholarmind.org",
        role="user",
        is_active=True
    )
