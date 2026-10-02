"""
Local API security: pairing token, origin allow-list, host check and request size limits.

The AURA API is a local developer service (bound to 127.0.0.1). It must not be callable by arbitrary web pages
the user visits (they could otherwise POST to localhost), so every /api request needs:
  - no Origin header (CLI / tests) or an allowed extension origin (chrome-extension://...), and
  - a Host header naming the loopback interface, or one listed in AURA_ALLOWED_HOSTS when the service is
    hosted (this check is the DNS-rebinding protection, so widening it is deliberate), and
  - the pairing token in the X-AURA-Token header (except GET /api/health, which reveals no secrets).
AI provider API keys never leave the server: no endpoint returns them and the extension never sends them.
"""
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Iterable, Optional

from aura.config import settings

TOKEN_FILE: Path = settings.BASE_DIR / ".aura_api_token"
TOKEN_HEADER = "x-aura-token"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def allowed_hosts() -> set:
    """
    Host names this service answers on.

    Loopback only unless AURA_ALLOWED_HOSTS names the public host it is deployed under. The Host check is
    what stops a web page the user visits from driving a service bound to their own machine, so a hosted
    deployment must name its host explicitly rather than accept any.
    """
    extra = {h.strip().lower() for h in os.getenv("AURA_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return LOOPBACK_HOSTS | extra
MAX_BODY_BYTES = 20 * 1024 * 1024  # evidence bundle incl. the viewport and full-page base64 PNGs


def load_or_create_token(path: Optional[Path] = None) -> str:
    """AURA_API_TOKEN from the environment, else a token persisted locally (created on first start)."""
    env = os.getenv("AURA_API_TOKEN", "").strip()
    if env:
        return env
    path = path or TOKEN_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 24:
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    if not settings.PERSIST:
        # Hosted: a per-process token would change on every restart, so AURA_API_TOKEN is expected.
        # Returning it unwritten keeps the process alive on a read-only filesystem.
        return token
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def token_matches(expected: str, supplied: Optional[str]) -> bool:
    return bool(supplied) and hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


# ---------------------------------------------------------------------------------------------------
# Per-install tokens
#
# A local install has one pairing token the user pastes once. A hosted service cannot: a single shared
# token would have to be published to be usable, which makes it no token at all. Instead each extension
# install asks for its own on first run, so there is no pairing step for the user at all.
#
# The token carries its own proof — an install id plus an HMAC of it under the server secret — so the
# server stores nothing. That matters on a host that sleeps and restarts: an in-memory list of issued
# tokens would be lost and every extension would be logged out, whereas a signed token keeps working
# across restarts and across instances.
# ---------------------------------------------------------------------------------------------------
INSTALL_TOKEN_PREFIX = "ai1"


def _signing_secret(api_token: str) -> bytes:
    """Derived from AURA_TOKEN_SECRET, else from the server token, so there is nothing extra to configure."""
    return (os.getenv("AURA_TOKEN_SECRET", "").strip() or api_token).encode("utf-8")


def issue_install_token(api_token: str) -> str:
    install_id = secrets.token_urlsafe(16)
    digest = hmac.new(_signing_secret(api_token), install_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{INSTALL_TOKEN_PREFIX}.{install_id}.{digest[:32]}"


def install_token_valid(api_token: str, supplied: Optional[str]) -> bool:
    parts = (supplied or "").split(".")
    if len(parts) != 3 or parts[0] != INSTALL_TOKEN_PREFIX:
        return False
    _, install_id, signature = parts
    expected = hmac.new(_signing_secret(api_token), install_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected[:32], signature)


def accepted(api_token: str, supplied: Optional[str]) -> bool:
    """The server's own token (local install, self-hosters) or a validly signed per-install token."""
    return token_matches(api_token, supplied) or install_token_valid(api_token, supplied)


def allowed_origins() -> list:
    """Comma-separated AURA_ALLOWED_ORIGINS (e.g. chrome-extension://<id>); default: any extension origin."""
    raw = os.getenv("AURA_ALLOWED_ORIGINS", "").strip()
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def origin_allowed(origin: Optional[str], allow_list: Iterable[str]) -> bool:
    if not origin:
        return True  # non-browser client (curl, tests); still needs the token
    origin = origin.rstrip("/")
    allow = list(allow_list)
    if allow:
        return origin in allow
    return origin.startswith("chrome-extension://")


def host_allowed(host_header: Optional[str]) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host in allowed_hosts()
