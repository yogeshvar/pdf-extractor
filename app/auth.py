"""HTTP Basic Auth middleware for public deployments."""

import base64
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

PUBLIC_PATHS = frozenset({"/health"})
REALM = "ArogyaNow Package Extractor"


def auth_enabled() -> bool:
    if os.environ.get("DISABLE_AUTH", "").lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("ACCESS_USERNAME") and os.environ.get("ACCESS_PASSWORD"))


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        content="Authentication required",
    )


def _check_credentials(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    username, _, password = decoded.partition(":")
    expected_user = os.environ.get("ACCESS_USERNAME", "")
    expected_pass = os.environ.get("ACCESS_PASSWORD", "")
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_pass
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if not _check_credentials(request.headers.get("authorization")):
            return _unauthorized()
        return await call_next(request)


def log_auth_status() -> None:
    if os.environ.get("DISABLE_AUTH", "").lower() in ("1", "true", "yes"):
        logger.warning("Auth disabled via DISABLE_AUTH")
    elif auth_enabled():
        logger.info("HTTP Basic Auth enabled")
    else:
        logger.warning(
            "Auth not configured — set ACCESS_USERNAME and ACCESS_PASSWORD "
            "(or DISABLE_AUTH=true for local dev only)"
        )
