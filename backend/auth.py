"""Shared auth/session helpers for the MVP."""

from __future__ import annotations

import secrets
import time
import warnings
from typing import TypedDict

from fastapi import Request

from backend.settings import settings

try:
    import bcrypt
except ImportError:
    bcrypt = None
    warnings.warn(
        "bcrypt is not installed. Password hashing will not work. "
        "Install it with: pip install bcrypt",
        RuntimeWarning,
        stacklevel=1,
    )


class SessionInfo(TypedDict):
    token: str
    user_id: int
    username: str
    expires_at: float


valid_sessions: dict[str, SessionInfo] = {}
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 30 * 60


def get_session_token() -> str:
    return secrets.token_urlsafe(32)


def create_session_token(user_id: int, username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_MAX_AGE
    valid_sessions[token] = {
        "token": token,
        "user_id": user_id,
        "username": username,
        "expires_at": expires_at,
    }
    return token


def hash_password(password: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed. Run: pip install bcrypt")
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed. Run: pip install bcrypt")
    password_bytes = password.encode("utf-8")
    hash_bytes = password_hash.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hash_bytes)


def verify_session(request: Request) -> SessionInfo | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    session = valid_sessions.get(token)
    if not session:
        return None

    if time.time() > session["expires_at"]:
        del valid_sessions[token]
        return None

    return session


def get_current_user(request: Request) -> SessionInfo | None:
    return verify_session(request)


def logout_session(token: str) -> bool:
    if token in valid_sessions:
        del valid_sessions[token]
        return True
    return False
