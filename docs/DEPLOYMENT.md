# Deploying AURA

Two pieces: the API, which verifies findings against the evidence, and the extension, which collects that
evidence and makes the AI call. They are deployed independently and the extension works against either a
hosted API or one on the user's own machine, so the fallback below costs a settings change rather than a
rewrite.

The API holds no provider API key on any path the extension uses. That is what makes a public deployment
reasonable: see [the privacy policy](../PRIVACY.md) for what it does hold.

## The API on Render

[`render.yaml`](../render.yaml) is a blueprint: point Render at this repository and it reads it.

```bash
# Build the image exactly as Render will, to see a failure here rather than there.
docker build -t aura-api .
docker run --rm -e PORT=8765 -e AURA_PERSIST=0 -e AURA_API_HOST=0.0.0.0 \
  -e AURA_API_TOKEN=local-smoke-test -p 8765:8765 aura-api
curl -s localhost:8765/api/health | head -c 200
```

### Environment

| Variable | Value | Why |
|---|---|---|
| `AURA_PERSIST` | `0` | Nothing is written to disk: no audit files, no screenshots, no token file. |
| `AURA_API_HOST` | `0.0.0.0` | The default is `127.0.0.1`, which a platform cannot route to. |
| `PORT` | injected by Render | Read automatically; `AURA_API_PORT` also works. |
| `AURA_ALLOWED_HOSTS` | the service's own hostname | The Host check is the defence against a web page driving the API, so a public deployment must name its host rather than accept any. Without this every request is `403 HOST_NOT_ALLOWED`. |
| `AURA_API_TOKEN` | a long random string, set in the dashboard | Signs the per-install tokens. Keep it out of the repository, and out of the logs: the server prints a token only when it is bound to loopback. |
| `AURA_ALLOWED_ORIGINS` | `chrome-extension://<the published id>` | Set it once the extension has a store id. Until then any extension origin is accepted, which is correct for development and too broad for production. |
| `AI_PROVIDER` | `mock` | The server makes no AI call on the extension's path. This only decides what the demo provider reports. |

### One instance

A scan is two requests — `prepare`, then `complete`, with the browser's model call in between — and the
prepared evidence waits in that process's memory. A second instance would answer `complete` without it and
the scan would have to start over. `render.yaml` pins `numInstances: 1`; scaling out means giving pending
scans somewhere shared to live first.

### The free tier sleeps

After about 15 minutes idle the instance stops, and the first scan afterwards waits for a cold start —
tens of seconds. `$7/month` removes it. Nothing is lost on sleep except audits held in memory, which were
never promised to survive.

## The extension

Three files name the service and must agree; `tests/test_hosted_deployment.py` fails if they do not:

- `extension/sidepanel/api.js` — `HOSTED_BACKEND`
- `extension/manifest.json` — `host_permissions`
- `render.yaml` — `AURA_ALLOWED_HOSTS`

Build a package:

```bash
python -m aura.tools.package_extension
```

It generates the icons (they are not committed), checks the manifest against the files that are actually
there, refuses to build if anything references something missing or loads remote code, and writes
`dist/aura-extension-<version>.zip`. Submitting it: [STORE-LISTING.md](STORE-LISTING.md).

## Verifying a deployment

In order, because each step rules out the failures that would confuse the next.

1. **It answers at all.** `curl -s https://<host>/api/health` returns JSON with `"status": "ok"`.

   Health is the one route that answers whatever Host it is asked on. That is not an oversight: the
   platform probes it from inside its own network to decide whether the service started, from an address
   no `AURA_ALLOWED_HOSTS` value could name in advance. The first deploy of this service failed for
   exactly that reason - `GET /api/health` from `10.228.25.132`, 403 every time, until the deploy timed
   out and rolled back. The Origin check still applies to health, so a web page cannot reach it.

   Every other route does enforce the Host check, so a `403 HOST_NOT_ALLOWED` from, say, `/api/providers`
   means `AURA_ALLOWED_HOSTS` does not name this host.
2. **It issues tokens.** `curl -s -X POST https://<host>/api/register -d '{}' -H 'Content-Type: application/json'`
   returns a token beginning `ai1.`.
3. **It refuses a key.** `curl -s -X POST https://<host>/api/providers/select -H "X-AURA-Token: <token>"
   -H 'Content-Type: application/json' -d '{"provider":"groq","api_key":"x"}'` returns
   `KEY_NOT_ACCEPTED`. This is the guarantee the privacy policy rests on.
4. **A real scan.** Load the extension pointed at the service, save a provider key, scan a page: findings
   appear, Highlight works, Screenshot shows a crop, Ask AURA answers.
5. **Nothing was written.** On Render, open a shell on the instance and check that `runs/` is absent or
   empty.

## Fallback: the service does not work out

Because the extension speaks to either backend and the AI call is in the browser either way, retreating
costs no code and no resubmission:

1. In ⚙ Settings, point the backend at `http://127.0.0.1:8765`.
2. Update the listing text and the privacy policy to say the server runs on the user's own machine — a
   listing edit, reviewed far faster than a new package.
3. Ship the server as a `pip install` or a one-file executable and link it from the listing.

Worth knowing: that is a weaker listing. An extension that needs a separately installed local server is a
common cause of "it doesn't work" reviews. It is a real safety net, not an equally good outcome.
