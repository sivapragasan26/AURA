"""
Local API security: pairing token, origin allow-list, host check and request size limits.

The AURA API is a local developer service (bound to 127.0.0.1). It must not be callable by arbitrary web pages
the user visits (they could otherwise POST to localhost), so every /api request needs:
  - no Origin header (CLI / tests) or an allowed extension origin (chrome-extension://...), and
  - a Host header naming the loopback interface (DNS-rebinding protection), and
  - the pairing token in the X-AURA-Token header (except GET /api/health, which reveals no secrets).
AI provider API keys never leave the server: no endpoint returns them and the extension never sends them.
"""
import hmac
import os
import secrets
from pathlib import Path
from typing import Iterable, Optional

from aura.config import settings

TOKEN_FILE: Path = settings.BASE_DIR / ".aura_api_token"
TOKEN_HEADER = "x-aura-token"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
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
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def token_matches(expected: str, supplied: Optional[str]) -> bool:
    return bool(supplied) and hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


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
    return host in LOOPBACK_HOSTS
