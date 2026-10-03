# Third-party notices

AURA itself is under the MIT licence ([LICENSE](LICENSE)). The components below are other people's work
and keep their own terms.

AURA ships one third-party component inside the extension and uses several Python packages on the server.
The component shipped inside the extension is listed first, because that is the one distributed to users
through the Chrome Web Store.

## Shipped in the extension

### axe-core 4.8.2 — Mozilla Public License 2.0

Copyright (c) 2015 – 2023 Deque Systems, Inc.

- File: `extension/vendor/axe.min.js`
- Licence: [`extension/vendor/LICENSE-axe-core-MPL-2.0.txt`](extension/vendor/LICENSE-axe-core-MPL-2.0.txt),
  the copy distributed by axe-core itself
- Source: <https://github.com/dequelabs/axe-core/tree/v4.8.2>
- Unmodified. It is vendored rather than loaded from a CDN so the extension runs no remote code, and
  `python -m aura.tools.sync_extension_assets` copies it from the engine's own copy so the two can never
  disagree. `tests/test_extension_assets.py` fails if the two differ.

The MPL requires that the licence travels with the file and that modifications are made available under
the same licence. AURA does not modify axe-core; if that ever changes, the modified file stays under the
MPL and the change must be published.

axe-core is used to run the accessibility checks in the page being scanned. The accessibility findings
AURA reports are derived from its results.

## Server dependencies (not distributed)

These run on the AURA service, or on the machine of anyone self-hosting it. They are installed from PyPI
and are not redistributed by AURA; each keeps its own licence.

| Package | Licence | Used for |
|---|---|---|
| starlette | BSD-3-Clause | the HTTP API |
| uvicorn | BSD-3-Clause | the ASGI server |
| pydantic | MIT | validating the evidence bundle |
| requests | Apache-2.0 | provider calls from the engine (self-hosted path) |
| pillow | MIT-CMU | per-finding screenshot crops (self-hosted path) |
| python-dotenv | BSD-3-Clause | reading `.env` on a self-hosted server |

beautifulsoup4 and lxml were listed as runtime dependencies but no module imports them; they were removed
rather than documented, which also keeps a compiled package out of the hosted image.

Development only, never deployed: pytest, playwright, streamlit, and the OpenAI, Google and Anthropic
Python SDKs. The hosted image installs `requirements.txt` only.

## What AURA does not ship

No remote code: the extension loads no script from a CDN and its content security policy allows
`script-src 'self'` only. No analytics, no tracking library, no fonts fetched at runtime.
