"""
Run the AURA API:  python -m aura.api

Binds 127.0.0.1 by default, so a local install behaves exactly as before. A hosted deployment sets
AURA_API_HOST=0.0.0.0 (and PORT, which the platform injects), AURA_ALLOWED_HOSTS to its public hostname,
AURA_API_TOKEN so no token file is written, and AURA_PERSIST=0 so nothing touches disk.
"""
import os

import uvicorn

from aura.api import security
from aura.api.server import configured_provider, create_app

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def main() -> None:
    # PORT is what most hosts inject; AURA_API_PORT stays the local knob.
    port = int(os.getenv("PORT") or os.getenv("AURA_API_PORT", "8765"))
    host = os.getenv("AURA_API_HOST", "127.0.0.1")
    token = security.load_or_create_token()
    provider, model = configured_provider()
    local = host in LOCAL_HOSTS

    print("=" * 64)
    print(f" AURA API  http://{host}:{port}   (AI provider: {provider}{' / ' + model if model else ''})")
    if local:
        # Printing the token is a convenience for a server only this machine can reach. On a hosted
        # deployment the same line would put a shared secret into the platform's log stream, so it is
        # printed only when the bind address is local.
        print(" Access token, if you point the extension here by hand (Settings):")
        print(f"   {token}")
        print(" Stored in .aura_api_token (git-ignored). Your AI provider key stays in the extension and")
        print(" goes only to that provider: this server never receives one.")
    else:
        print(f" Reachable on: {', '.join(sorted(security.allowed_hosts()))}")
        print(" Token not printed: set AURA_API_TOKEN and read it from your platform's secret store.")
    print("=" * 64)
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
