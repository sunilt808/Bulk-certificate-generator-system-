import secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings


def require_api_key(
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    if not settings.API_KEY:
        return
    if not api_key or not secrets.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
