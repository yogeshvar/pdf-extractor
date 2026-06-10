"""HTTP Basic Auth and session-cookie auth for public deployments."""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

logger = logging.getLogger(__name__)

PUBLIC_PATHS = frozenset({"/health", "/login", "/login.html", "/api/login"})
PUBLIC_ASSET_SUFFIXES = (".css", ".js", ".ico", ".png", ".svg", ".woff", ".woff2")
SESSION_COOKIE = "arogya_session"
SESSION_MAX_AGE = 7 * 24 * 3600


def is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return path.endswith(PUBLIC_ASSET_SUFFIXES)


def auth_enabled() -> bool:
    if os.environ.get("DISABLE_AUTH", "").lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("ACCESS_USERNAME") and os.environ.get("ACCESS_PASSWORD"))


def _session_secret() -> bytes:
    user = os.environ.get("ACCESS_USERNAME", "")
    password = os.environ.get("ACCESS_PASSWORD", "")
    return hashlib.sha256(f"{user}:{password}".encode()).digest()


def create_session_token() -> str:
    exp = int(time.time()) + SESSION_MAX_AGE
    payload = str(exp)
    sig = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        exp_str, sig = token.split(".", 1)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False
    if time.time() > exp:
        return False
    expected = hmac.new(_session_secret(), exp_str.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(sig, expected)


def credentials_valid(username: str, password: str) -> bool:
    expected_user = os.environ.get("ACCESS_USERNAME", "")
    expected_pass = os.environ.get("ACCESS_PASSWORD", "")
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_pass
    )


def _unauthorized(request: Request) -> Response:
    path = request.url.path
    is_api = path.startswith("/api/")

    accept = request.headers.get("accept", "")
    if "text/html" in accept and not is_api and path not in ("/login", "/login.html"):
        next_url = path
        if request.url.query:
            next_url += "?" + request.url.query
        return RedirectResponse(f"/login?next={quote(next_url)}", status_code=302)

    if is_api:
        return Response(
            status_code=401,
            content='{"detail":"Authentication required"}',
            media_type="application/json",
        )
    return Response(status_code=401, content="Authentication required")


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
    return credentials_valid(username, password)


def _is_authenticated(request: Request) -> bool:
    if _check_credentials(request.headers.get("authorization")):
        return True
    return verify_session_token(request.cookies.get(SESSION_COOKIE))


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)
        if is_public_path(request.url.path):
            return await call_next(request)
        if not _is_authenticated(request):
            return _unauthorized(request)
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
