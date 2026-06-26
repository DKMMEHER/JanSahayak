import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_sahayak.config import get_settings
from jan_sahayak.database import get_db
from jan_sahayak.models.user import User
from jan_sahayak.logger import get_logger

# Firebase Admin SDK imports
import firebase_admin
from firebase_admin import credentials as firebase_credentials, auth as firebase_auth

logger = get_logger(__name__)
settings = get_settings()

security = HTTPBearer()

_firebase_initialized = False


def init_firebase():
    """Lazy initialize Firebase Admin SDK using credential file if available."""
    global _firebase_initialized
    if _firebase_initialized:
        return

    cred_path = settings.firebase_credentials_path
    if os.path.exists(cred_path):
        try:
            cred = firebase_credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            logger.info("Firebase Admin initialized successfully using service account JSON credentials.")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}", exc_info=True)
    else:
        logger.warning(f"Firebase credentials JSON not found at: {cred_path}. Attempting default initialization.")
        try:
            firebase_admin.initialize_app()
            _firebase_initialized = True
            logger.info("Firebase Admin initialized using default credentials.")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin with default credentials: {e}", exc_info=True)


def create_access_token(user_id: str) -> str:
    """
    Generate a JWT token for the user (only used in local authentication mode).
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expiry_minutes)
    to_encode = {"sub": user_id, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm="HS256")
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and verify a local JWT token.
    Returns the payload if valid, otherwise None.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency to protect routes and fetch the current user.
    Supports local JWT token verification and Firebase ID token verification.
    """
    token = credentials.credentials

    # Case 1: Firebase Authentication
    if settings.auth_provider == "firebase":
        init_firebase()
        try:
            decoded_token = firebase_auth.verify_id_token(token)
            phone_number = decoded_token.get("phone_number")
            if not phone_number:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Firebase token: phone number not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Standardize phone number format (strip country code +91)
            clean_phone = phone_number.strip()
            if clean_phone.startswith("+91"):
                clean_phone = clean_phone[3:]
            elif clean_phone.startswith("91") and len(clean_phone) > 10:
                clean_phone = clean_phone[2:]

            # Fetch or auto-register user in the local database
            result = await db.execute(select(User).where(User.phone == clean_phone))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    phone=clean_phone,
                    name=decoded_token.get("name") or f"Citizen {clean_phone[-4:]}",
                    preferred_language="hindi",
                )
                db.add(user)
                await db.commit()
                # Fetch again to populate database-generated attributes
                result = await db.execute(select(User).where(User.phone == clean_phone))
                user = result.scalar_one_or_none()

            return user

        except Exception as e:
            logger.warning(f"Firebase token verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not validate Firebase credentials: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Case 2: Local Authentication (Default)
    payload = verify_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload["sub"]
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
