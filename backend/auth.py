# auth.py
# Password hashing, JWT token generation, and the get_current_user dependency.
#
# Why JWT and not sessions?
# JWT tokens are stateless — the backend does not need to store anything to
# verify a token. The token itself contains the user's ID, signed with a secret
# key. On each protected request, the backend verifies the signature and reads
# the user ID from the token. This is the correct approach for a REST API that
# will be consumed by a separate frontend (Vercel) talking to a separate backend
# (Railway).

from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import os

from database import get_db
import models

# Secret key used to sign JWT tokens. In production this must be a long random
# string stored in the environment — never hardcoded. Generate one with:
#   python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is not set. "
        "Add it to your .env file."
    )

# Warn loudly when a well-known dev placeholder is used so it cannot be
# silently deployed to production. We don't refuse to start (that would break
# a fresh clone), but the message is unmissable in server logs.
_KNOWN_INSECURE_KEYS = {
    "replace-with-a-64-char-hex-secret",
    "dev-mediscribe-secret-key-32-chars-long-jwt-token",
}
if SECRET_KEY in _KNOWN_INSECURE_KEYS:
    import logging as _logging
    _logging.getLogger("mediscribe.auth").warning(
        "JWT_SECRET_KEY is a well-known insecure placeholder — all tokens are "
        "trivially forgeable. Generate a real key: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )

ALGORITHM     = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7   # 7 days — reasonable for a medical app

# CryptContext handles password hashing and verification.
# bcrypt is the industry standard — it is slow by design (brute-force resistant).
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTPBearer reads the Authorization: Bearer <token> header.
bearer_scheme = HTTPBearer()


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    """
    Create a signed JWT token containing the user's ID.
    The token expires after ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),   # "sub" (subject) is the standard JWT claim for user identity
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token_user_id(token: str) -> Optional[int]:
    """Safely decode JWT token and extract the user ID subject integer."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    FastAPI dependency for protected routes. Reads the Bearer token from the
    Authorization header, verifies the signature and expiry, fetches the user
    from the database, and returns the User ORM object.

    If the token is missing, invalid, or expired — raises 401 Unauthorized.

    Usage in a route:
        @app.get("/api/protected")
        def protected(current_user: models.User = Depends(get_current_user)):
            return {"user_id": current_user.id}
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception

    return user


optional_bearer_scheme = HTTPBearer(auto_error=False)


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """
    Optional user dependency. If valid bearer token is present, returns User.
    Otherwise returns None without raising an HTTPException.
    """
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
        if user and user.is_active:
            return user
    except Exception:
        pass
    return None