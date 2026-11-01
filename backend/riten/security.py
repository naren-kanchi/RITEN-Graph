"""Password hashing, signed session tokens, and server-side role checks."""
import datetime as dt

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Cookie, Depends, HTTPException, status

from . import db
from .config import get_settings

COOKIE_NAME = "riten_session"
_hasher = PasswordHasher()
# Verified when the username is unknown, so response time does not reveal which names exist.
_DUMMY_HASH = _hasher.hash("riten-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        ok = _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None


def issue_token(user_id: int) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + dt.timedelta(minutes=s.jwt_ttl_minutes)},
                      s.jwt_secret, algorithm="HS256")


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")


def current_user(riten_session: str | None = Cookie(default=None)) -> dict:
    """The role is read from the database on each request, so deactivation applies immediately."""
    if not riten_session:
        raise _unauthorized()
    try:
        claims = jwt.decode(riten_session, get_settings().jwt_secret, algorithms=["HS256"])
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized() from None
    user = db.fetch_one("SELECT user_id, username, role FROM app_user WHERE user_id = %s AND is_active", (user_id,))
    if user is None:
        raise _unauthorized()
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required.")
    return user
