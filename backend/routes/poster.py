import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import RedirectResponse

from backend.settings import settings
from backend.storage import _get_level, _get_session_profile

router = APIRouter()


def _get_user_id(request: Request, x_session_id: str | None = None) -> str:
    """Get user identifier from authenticated session or fallback to header/UUID."""
    current_user = getattr(request.state, "current_user", None)
    if current_user and current_user.get("user_id"):
        return str(current_user["user_id"])
    return x_session_id or str(uuid.uuid4())


@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "ollama_available": getattr(request.app.state, "ollama_available", False),
        "db_available": getattr(request.app.state, "db_available", False),
        "cache": "redis" if getattr(request.app.state, "redis", None) else "memory",
        "use_ollama": settings.is_ollama_enabled(request),
        "pgvector": True,
    }

@router.get("/api/level", tags=["Poster"])
async def api_level(request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    session_id = _get_user_id(request, x_session_id)
    profile = await _get_session_profile(session_id)
    level = str(profile.get("level") or await _get_level(session_id))
    return {
        "session_id": session_id,
        "level": level,
        "focus": profile.get("focus"),
        "error_rates": profile.get("error_rates", {}),
        "total_attempts": profile.get("total_attempts", 0),
        "success_rate": profile.get("success_rate", 0.0),
    }


@router.get("/api/session", tags=["Poster"])
async def api_session(request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    session_id = _get_user_id(request, x_session_id)
    profile = await _get_session_profile(session_id)
    return {"session_id": session_id, **profile}


@router.get("/")
def root():
    return RedirectResponse(url="/app/")
