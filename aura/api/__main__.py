"""Run the AURA local API:  python -m aura.api   (binds 127.0.0.1 only)."""
import os

import uvicorn

from aura.api import security
from aura.api.server import configured_provider, create_app


def main() -> None:
    port = int(os.getenv("AURA_API_PORT", "8765"))
    token = security.load_or_create_token()
    provider, model = configured_provider()
    print("=" * 64)
    print(f" AURA API  http://127.0.0.1:{port}   (AI provider: {provider}{' / ' + model if model else ''})")
    print(" Pairing token (paste into the AURA extension > Settings):")
    print(f"   {token}")
    print(" The token is stored in .aura_api_token (git-ignored). Provider API keys stay on this server.")
    print("=" * 64)
    uvicorn.run(create_app(token=token), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
