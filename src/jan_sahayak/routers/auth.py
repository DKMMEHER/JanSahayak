"""
Authentication router — handles login, registration, and user session details.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.config import get_settings
from jan_sahayak.database import get_db
from jan_sahayak.models.user import User
from jan_sahayak.schemas.api import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from jan_sahayak.services.auth import create_access_token, get_current_user
from jan_sahayak.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse)
async def register_user(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a new citizen with phone and optional name.
    Returns JWT token and user info.
    """
    if settings.auth_provider == "firebase":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is managed by Firebase. Send Firebase ID token in Authorization header instead.",
        )

    # Check if user already exists
    result = await db.execute(select(User).where(User.phone == request.phone))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this phone number is already registered.",
        )

    # Create new user
    new_user = User(
        phone=request.phone,
        name=request.name,
        preferred_language="hindi",  # Default preferred language
    )
    db.add(new_user)
    await db.flush()  # Populates user.id

    token = create_access_token(new_user.id)
    logger.info(f"Registered new user with phone {request.phone}, id {new_user.id}")

    return AuthResponse(
        access_token=token,
        user=UserResponse.model_validate(new_user),
    )


@router.post("/login", response_model=AuthResponse)
async def login_user(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Log in a citizen using phone and OTP.
    For local development, any 4-6 digit OTP is accepted.
    """
    if settings.auth_provider == "firebase":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is managed by Firebase. Send Firebase ID token in Authorization header instead.",
        )

    # Check if user exists
    result = await db.execute(select(User).where(User.phone == request.phone))
    user = result.scalar_one_or_none()

    if not user:
        # Auto-register user on first login if not found to make testing seamless
        logger.info(f"Auto-registering user during login for phone: {request.phone}")
        user = User(
            phone=request.phone,
            name=f"User {request.phone[-4:]}",
            preferred_language="hindi",
        )
        db.add(user)
        await db.flush()
    else:
        logger.info(f"Logging in user: {request.phone}")

    # Generate token
    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Get the current logged-in user profile.
    """
    return UserResponse.model_validate(current_user)
