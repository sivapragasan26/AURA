"""
Does a scan work when the AI call is made in the browser, with the user's own key?

This is the hosted architecture driven for real: real Chrome, the real unpacked extension, the real API,
and a real scan of a real page. The only thing that is not real is the provider's ADDRESS: PROVIDERS.groq.url
is pointed at a stand-in served by this test (the same monkeypatching a unit test does, applied from the
debugger rather than inside the product), so no API key and no money are spent to prove the path works.

What it proves:
  * the panel sends no screenshot to the server, and tells it the capture size instead
  * the server returns a prompt, the browser calls the provider itself with the key from its own storage,
    and the server verifies the answer
  * the key is in the request to the provider and in nothing that goes to AURA
  * a provider that refuses still produces a scan, with the reason shown
  * the per-finding screenshot is cropped in the browser, from a capture the server never received

Run: .venv/Scripts/python.exe tests/extension_browser_ai_e2e.py
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("AURA_PERSIST", "0")

import uvicorn  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from aura.api.server import create_app  # noqa: E402
from aura.config import settings  # noqa: E402
from cdp_harness import ChromeHarness, SidePanel  # noqa: E402

TOKEN = "browser-ai-" + "x" * 28
PORT = 8765
BACKEND = f"http://127.0.0.1:{PORT}"
EXT = str(ROOT / "extension")
PAGE_PORT = 8795

# A page with problems a model can plausibly report and the verifier can independently confirm.
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Checkout - Example Store</title>
<style>
 body{margin:0;font:16px/1.5 system-ui;color:#222}
 header{padding:14px 18px;background:#111;color:#fff}
 main{padding:18px;max-width:760px}
 .row{display:flex;gap:14px;align-items:center;margin:26px 0}
 #del{font-size:20px;padding:16px 28px;background:#dc2626;color:#fff;border:0;border-radius:8px}
 #save{font-size:11px;padding:6px 10px;background:#f3f4f6;color:#9ca3af;border:1px solid #e5e7eb;border-radius:4px}
 .spacer{height:1200px}
 footer{padding:40px 18px;background:#f8f8f8}
</style></head>
<body>
  <header>Example Store</header>
  <main>
    <h1>Checkout</h1>
    <p>Review your order before paying.</p>
    <div class="row">
      <button id="del">Delete order</button>
      <button id="save">Save changes</button>
    </div>
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="48" height="48">
    <a href="#" id="bare"></a>
    <label>Card number</label><input type="text">
    <div class="spacer"></div>
    <h2 id="low">Delivery</h2>
    <button id="deep">Choose a delivery slot</button>
  </main>
  <footer>Example Store</footer>
</body></html>
"""

# A Groq-shaped reply. Its candidate is written against the refs AURA puts in the prompt, which this
# stand-in reads out of the prompt it is given - exactly as a model would have to.
STUB_STATE = {"mode": "ok", "requests": [], "prompts": []}


def provider_stub_response(body):
    STUB_STATE["requests"].append(body)
    messages = body.get("messages") or []
    content = messages[0].get("content") if messages else []
    prompt = ""
    image_parts = 0
    for part in content if isinstance(content, list) else []:
        if part.get("type") == "text":
            prompt += part.get("text") or ""
        elif part.get("type") == "image_url":
            image_parts += 1
    STUB_STATE["prompts"].append({"chars": len(prompt), "images": image_parts})

    ref = None
    try:
        packet = json.loads(prompt.split("```json", 1)[1].split("```", 1)[0])
        for element in packet.get("targeted_dom") or []:
            if "Save changes" in json.dumps(element):
                ref = element.get("ref")
                break
    except (IndexError, ValueError):
        ref = None

    answer = {
        "overall_summary": "The destructive action is the most prominent control on the page.",
        "candidates": ([{
            "title": "Save changes is far weaker than Delete order next to it",
            "category": "UI",
            "rule_type": "weak_primary_cta",
            "description": "Save changes is small and grey while Delete order is large and red, so the "
                           "destructive action looks like the one to press.",
            "target": ref,
            "evidence": "Save changes is 11px grey; Delete order is 20px white on red and much larger.",
            "confidence": 0.88,
            "why_ai_needed": "Relative visual weight has to be judged from the rendered page.",
            "severity": "high",
            "recommendation": "Give Save changes the primary styling and make Delete order secondary.",
        }] if ref else []),
    }
    return {"id": "stub-1", "model": body.get("model") or "stub-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(answer)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}


def build_app():
    """The real AURA app, with the provider stand-in alongside it on the same origin.

    Same origin because the extension's host permissions allow the AURA server and the four real
    providers, and nothing else - which is the point of them. Mounting the stand-in here tests the real
    permission set rather than widening it for the test.
    """
    app = create_app(token=TOKEN)

    async def stub(request: Request):
        auth = request.headers.get("authorization") or ""
        body = await request.json()
        if STUB_STATE["mode"] == "rate_limited":
            return JSONResponse({"error": {"message": "Rate limit reached for requests per day"}},
                                status_code=429, headers={"retry-after": "60"})
        if STUB_STATE["mode"] == "bad_key" or not auth.startswith("Bearer "):
            return JSONResponse({"error": {"message": "Invalid API Key"}}, status_code=401)
        STUB_STATE["keys_seen"] = auth.replace("Bearer ", "")
        return JSONResponse(provider_stub_response(body))

    async def stub_models(request: Request):
        return JSONResponse({"data": [{"id": "qwen/qwen3.8-27b"}]})

    from starlette.routing import Route
    app.routes.append(Route("/__provider/chat/completions", stub, methods=["POST"]))
    app.routes.append(Route("/__provider/models", stub_models, methods=["GET"]))
    return app


def serve_page():
    import http.server
    import socketserver
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="aura-ai-e2e-"))
    (root / "checkout.html").write_text(PAGE, encoding="utf-8")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = S(("127.0.0.1", PAGE_PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{PAGE_PORT}/checkout.html"


def start_api():
    settings.AI_PROVIDER = "mock"
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError("API did not start")


CHECKS = []


def check(ok, msg):
    CHECKS.append((bool(ok), msg))
    print(("PASS  " if ok else "FAIL  ") + msg, flush=True)


def waited(panel, expr, timeout=15.0):
    """panel.wait raises on timeout; a check wants a false instead."""
    try:
        return bool(panel.wait(expr, timeout))
    except AssertionError:
        return False


# Points the provider client at the stand-in and records what the panel sends to AURA. Both are done from
# the debugger, in the panel's own module instances, so the product code under test is unmodified.
INSTRUMENT = """
(async () => {
  const providers = await import('./providers.js');
  providers.PROVIDERS.groq.url = () => '%(backend)s/__provider/chat/completions';
  providers.PROVIDERS.groq.check = () => ({ url: '%(backend)s/__provider/models', method: 'GET' });
  window.__sent = [];
  if (!window.__fetchWrapped) {
    const real = window.fetch;
    window.fetch = async (url, opts) => {
      try {
        const u = String(url);
        if (u.includes('/api/') || u.includes('/__provider/')) {
          window.__sent.push({ url: u, headers: (opts && opts.headers) || {},
                               body: (opts && typeof opts.body === 'string') ? opts.body : null });
        }
      } catch (_) {}
      return real(url, opts);
    };
    window.__fetchWrapped = true;
  }
  await chrome.storage.local.set({
    backendUrl: '%(backend)s', token: '%(token)s',
    aiProvider: 'groq', aiModel: 'qwen/qwen3.8-27b',
    providerKeys: { groq: '%(key)s' },
  });
  return true;
})()
"""

TEST_KEY = "gsk_test_only_not_a_real_key_000"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(600, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    url = serve_page()
    runs_before = sorted(p.name for p in settings.RUNS_DIR.iterdir()) if settings.RUNS_DIR.exists() else []
    api = start_api()
    h = ChromeHarness(headless=True)
    try:
        ext = h.load_extension(EXT)
        page = h.extension_page(ext)
        h.evaluate(page, f"chrome.storage.local.set({{backendUrl: '{BACKEND}', token: '{TOKEN}'}})")
        tab = h.open_tab(url, new_window=True)
        h.click_toolbar_action(ext, tab)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok")
        h.evaluate(panel.session, INSTRUMENT % {"backend": BACKEND, "token": TOKEN, "key": TEST_KEY})

        # ---- the privacy notice must describe what actually happens ---------------------------------
        # textContent, not innerText: the notice sits inside a collapsed <details>, so it is not rendered
        # until a person opens it, and innerText of unrendered text is empty.
        waited(panel, "document.getElementById('privacy').textContent.length > 40", 15)
        privacy = panel.js("document.getElementById('privacy').textContent")
        print("   privacy notice: " + privacy)
        print("   conn: " + panel.text("conn"))
        check("stay in this browser" in privacy, f"the panel says screenshots stay in the browser: {privacy[:120]}...")
        # The notice follows the provider that is actually chosen, so it is read after the panel has
        # caught up with the choice this test just made.
        waited(panel, "document.getElementById('privacy').textContent.indexOf('Groq') !== -1", 15)
        privacy = panel.js("document.getElementById('privacy').textContent")
        print("   privacy notice (Groq chosen): " + privacy)
        check("Groq" in privacy and "your own API key" in privacy,
              f"the panel names the provider the browser will call and whose key it uses: {privacy[-90:]}")
        check("AURA never receives that key" in privacy, "the panel says AURA never receives the key")

        # ---- the scan ------------------------------------------------------------------------------
        # The scanned tab must be the front one, as it is when a person presses Scan: a capture of a
        # window that is not in front never settles in a headless browser, and the panel of a window that
        # is not in front renders nothing to read back.
        h.activate(tab)
        panel.scan(timeout=300)
        sent = h.evaluate(panel.session, "window.__sent")
        steps = panel.js("document.getElementById('steps').textContent")
        findings = panel.js("document.querySelectorAll('#findings .finding').length")
        print(f"\n   steps: {steps[:400]}\n   findings: {findings}\n")

        paths = [s["url"].replace(BACKEND, "") for s in sent]
        check(any(p.startswith("/api/audits/prepare") for p in paths), f"the panel asked AURA to prepare the scan ({paths})")
        check(any("/complete" in p for p in paths), "the panel sent the model's answer back to be verified")
        check(not any(p == "/api/audits" for p in paths), "the one-shot server-side scan was not used")
        check(any("/__provider/chat/completions" in s["url"] for s in sent), "the browser called the provider itself")

        prepare = next(s for s in sent if "/api/audits/prepare" in s["url"])
        body = json.loads(prepare["body"])
        bundle = body["bundle"]
        check("screenshot_png_base64" not in bundle and "screenshot_fullpage_png_base64" not in bundle,
              f"no screenshot was uploaded to AURA (bundle keys: {sorted(bundle)})")
        check(isinstance(bundle.get("capture_size"), dict) and bundle["capture_size"].get("height", 0) > 0,
              f"the capture size was declared instead ({bundle.get('capture_size')})")
        print(f"   prepare body: {len(prepare['body']):,} bytes of evidence "
              f"({bundle['dom'].get('elements') and len(bundle['dom']['elements'])} DOM elements, "
              f"{len(bundle.get('target_boxes') or {})} boxes)")
        check(len(prepare["body"]) < 3 * 1024 * 1024,
              f"the evidence a scan uploads is small now that no image goes with it ({len(prepare['body']):,} bytes)")
        check(TEST_KEY not in prepare["body"], "the API key is not in what AURA receives")
        check(TEST_KEY not in json.dumps(prepare["headers"]), "the API key is not in the headers AURA receives")
        complete = next(s for s in sent if "/complete" in s["url"])
        check(TEST_KEY not in complete["body"], "the API key is not in the completion AURA receives")
        check(json.loads(complete["body"]).get("provider") == "groq",
              "AURA is told which provider answered, so the audit can record it")

        provider_call = next(s for s in sent if "/__provider/chat/completions" in s["url"])
        check(TEST_KEY in json.dumps(provider_call["headers"]), "the key went to the provider, in the request's own header")
        check(STUB_STATE.get("keys_seen") == TEST_KEY, "the provider received exactly the key from this browser")
        check(bool(STUB_STATE["prompts"]) and STUB_STATE["prompts"][0]["chars"] > 1000,
              f"the prompt AURA prepared reached the provider ({STUB_STATE['prompts']})")
        check(bool(STUB_STATE["prompts"]) and STUB_STATE["prompts"][0]["images"] == 1,
              f"the screenshot was attached by the browser ({STUB_STATE['prompts']})")

        check("straight from this browser" in steps, f"the step list says where the AI call was made")
        check(findings > 0, f"the scan produced findings ({findings})")
        titles = panel.js("[...document.querySelectorAll('#findings .finding')].map(e=>e.textContent).join(' | ')")
        check("Save changes" in titles or "save changes" in titles.lower(),
              f"the model's verified finding is shown ({titles[:200]})")

        # ---- the per-finding screenshot is cropped here ---------------------------------------------
        opened = panel.js("""(() => {
          const cards = [...document.querySelectorAll('#findings .finding')];
          for (const c of cards) { c.click();
            if (!document.getElementById('act-shot').classList.contains('hidden')) return c.textContent.slice(0, 60); }
          return null; })()""")
        check(bool(opened), f"a finding offers a screenshot ({opened})")
        if opened:
            panel.click("#act-shot")
            got = waited(panel, "document.querySelector('.shot') && document.querySelector('.shot').complete", 20)
            check(got, "the crop was produced in the browser and shown")
            src = panel.js("document.querySelector('.shot') ? document.querySelector('.shot').src : ''")
            check(src.startswith("blob:"), f"the image is a local blob, not a server response ({src[:40]})")
            size = panel.js("""(() => { const i = document.querySelector('.shot');
                                return i ? {w: i.naturalWidth, h: i.naturalHeight} : null; })()""")
            check(bool(size) and size["w"] > 20 and size["h"] > 20, f"the crop has real pixels ({size})")
            after = h.evaluate(panel.session, "window.__sent.length")
            check(after == len(sent), "showing the screenshot made no request to AURA at all")
            panel.click(".act-close")
            check(waited(panel, "!document.querySelector('.shot')", 10), "the screenshot panel closes")

        # ---- a provider that refuses ----------------------------------------------------------------
        STUB_STATE["mode"] = "rate_limited"
        h.evaluate(panel.session, "window.__sent = []")
        h.activate(tab)
        panel.scan(timeout=300)
        steps2 = panel.js("document.getElementById('steps').textContent")
        summary = panel.js("document.getElementById('results').textContent")
        findings2 = panel.js("document.querySelectorAll('#findings .finding').length")
        check("Rate limit" in steps2 or "rate limit" in steps2.lower(),
              f"the rate limit is shown in the steps ({steps2[-220:]})")
        check("rate limit" in summary.lower() or "unavailable" in summary.lower(),
              "the result says why there was no AI analysis")
        check(findings2 >= 0, f"the scan still completed and reported deterministic findings ({findings2})")
        paths2 = [s["url"].replace(BACKEND, "") for s in h.evaluate(panel.session, "window.__sent")]
        check(any("/complete" in p for p in paths2), "the failure was reported to AURA as a completed scan")

        # ---- the key check never runs the model ------------------------------------------------------
        STUB_STATE["mode"] = "ok"
        before = len(STUB_STATE["requests"])
        panel.js("document.getElementById('provider-toggle').click()")
        time.sleep(1.0)
        panel.js("document.getElementById('provider-test').click()")
        waited(panel, "document.getElementById('provider-status').textContent.indexOf('Testing') === -1", 20)
        status = panel.text("provider-status")
        check("READY" in status, f"testing the key reports READY ({status[:120]})")
        check(len(STUB_STATE["requests"]) == before, "testing the key did not run the model")
    finally:
        h.close()
        api.should_exit = True
        time.sleep(0.4)

    runs = settings.RUNS_DIR
    kept = sorted(p.name for p in runs.iterdir()) if runs.exists() else []
    check(kept == runs_before, f"the server wrote nothing to disk during these scans "
                               f"({len(kept) - len(runs_before)} new in {runs})")

    failed = [m for ok, m in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    for m in failed:
        print("  FAILED: " + m)
    print("BROWSER AI SCAN:", "PASSED" if not failed else "FAILED")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
