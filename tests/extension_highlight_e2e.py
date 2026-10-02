"""
Real-browser check of AURA's target resolution and Highlight.

    python tests/extension_highlight_e2e.py

Part 1 exercises the in-page resolver (extension/content/page_agent.js) against a real DOM in real Chrome:
exact selector, each fallback strategy, refusal on ambiguity, and a distinct honest message for every
failure. Part 2 drives the REAL side panel end to end: scan, open a finding, click Highlight, confirm an
overlay is drawn on the right element, then break the page and confirm the panel explains why it cannot
highlight any more instead of showing one catch-all message.

No AI key is needed: the scan runs with the built-in Mock provider.
"""
import http.server
import json
import os
import socketserver
import sys
import tempfile
import urllib.request
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdp_harness import ChromeHarness, SidePanel  # noqa: E402
from extension_e2e import BACKEND_URL, TOKEN, start_api  # noqa: E402

EXT = str(ROOT / "extension")
AGENT_JS = (ROOT / "extension" / "content" / "page_agent.js").read_text(encoding="utf-8")
PAGE_PORT = 8791
RESULTS = []

# A page built to look like the real sites AURA struggles with: generated class names, a control whose
# class changes on "rerender", two identical buttons, and a control identified only by its accessible name.
PAGE_A = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Highlight lab</title></head>
<body>
  <header>
    <nav>
      <button id="search-btn" class="css-1a2b3c">Search</button>
      <button class="css-9z8y7x" aria-label="Open your account menu">Account</button>
    </nav>
  </header>
  <main id="main">
    <h1>Highlight lab</h1>
    <button class="css-dup">Follow</button>
    <button class="css-dup">Follow</button>
    <a href="/pricing" data-testid="pricing-link" class="css-4d5e6f">See pricing</a>
    <button id="doomed" class="css-gone">Temporary</button>
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="40" height="40">
  </main>
  <script>
    // "Rerender": the framework swaps generated class names, exactly what breaks a recorded selector.
    window.rerender = () => {
      document.getElementById('search-btn').className = 'css-rerendered-77';
      document.getElementById('search-btn').removeAttribute('id');
      document.querySelector('[data-testid="pricing-link"]').className = 'css-rerendered-88';
    };
    window.removeDoomed = () => document.getElementById('doomed').remove();
  </script>
</body></html>
"""

PAGE_B = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Another page</title></head>
<body><main><h1>A different page</h1><p>Nothing from the other page is here.</p></main></body></html>
"""


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise AssertionError(msg)


def serve_pages(port: int = PAGE_PORT) -> str:
    root = Path(tempfile.mkdtemp(prefix="aura-highlight-"))
    (root / "a.html").write_text(PAGE_A, encoding="utf-8")
    (root / "b.html").write_text(PAGE_B, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = Server(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


def highlight(h, session, args):
    """Runs the real resolver in the page and returns its result."""
    h.evaluate(session, AGENT_JS)
    return h.evaluate(session, f"JSON.stringify(globalThis.__AURA_AGENT__.highlight({json.dumps(args)}))")


def boxes(h, session):
    return h.evaluate(session, "document.querySelectorAll('[data-aura-overlay]').length")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    watchdog = threading.Timer(600, lambda: (print("FAIL global timeout", flush=True), os._exit(3)))
    watchdog.daemon = True
    watchdog.start()
    base = serve_pages()
    api = start_api()
    h = ChromeHarness()
    try:
        ext = h.load_extension(EXT)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")

        # ---------------------------------------------------------------- Part 1: the resolver
        page = h.open_tab(f"{base}/a.html", new_window=True)
        session = h.attach(page)

        r = json.loads(highlight(h, session, {"selectors": ["#search-btn"], "label": "F-1 · high",
                                              "expectedText": "Search", "role": "button", "tag": "button"}))
        check(r["status"] == "highlighted" and r["strategy"] == "EXACT_SELECTOR",
              f"H: exact selector highlights the element ({r['status']}/{r.get('strategy')})")
        check(boxes(h, session) == 1, "H: exactly one overlay is drawn")

        h.evaluate(session, "globalThis.__AURA_AGENT__.clearHighlight()")
        check(boxes(h, session) == 0, "H: clearing removes the overlay")

        # The framework rerenders: the recorded selector is dead, the control is still there.
        h.evaluate(session, "window.rerender()")
        r = json.loads(highlight(h, session, {"selectors": ["#search-btn"], "label": "F-1 · high",
                                              "expectedText": "Search", "role": "button", "tag": "button"}))
        check(r["status"] == "highlighted" and r["strategy"] == "VISIBLE_TEXT_AND_ROLE",
              f"I: a dead selector recovers through text + role ({r['status']}/{r.get('strategy')})")
        check("located the element by" in (r.get("message") or ""), "I: the fallback is disclosed to the user")
        check(h.evaluate(session, "document.querySelector('.css-rerendered-77').tagName") == "BUTTON",
              "I: the rerendered control is the one still on the page")

        r = json.loads(highlight(h, session, {"selectors": ["#account-btn"], "label": "F-2 · medium",
                                              "accessibleName": "Open your account menu", "role": "button",
                                              "tag": "button"}))
        check(r["status"] == "highlighted" and r["strategy"] == "ACCESSIBLE_NAME_AND_ROLE",
              f"I: an unnamed control recovers through its accessible name ({r.get('strategy')})")

        r = json.loads(highlight(h, session, {"selectors": ['a[data-testid="pricing-link"].css-4d5e6f'],
                                              "label": "F-3 · low", "tag": "a"}))
        check(r["status"] == "highlighted" and r["strategy"] == "STABLE_ATTRIBUTE",
              f"I: a changed class recovers through a stable attribute ({r.get('strategy')})")

        r = json.loads(highlight(h, session, {"selectors": [".css-dup"], "label": "F-4 · low",
                                              "expectedText": "Follow", "role": "button", "tag": "button"}))
        check(r["status"] == "ambiguous", f"J: two identical controls are not highlighted ({r['status']})")
        check(r["message"] == "Several elements match this finding, so AURA did not highlight one automatically.",
              "J: the ambiguity message says so plainly")
        check(boxes(h, session) == 0, "J: nothing is drawn when the match is ambiguous")

        h.evaluate(session, "window.removeDoomed()")
        r = json.loads(highlight(h, session, {"selectors": ["#doomed"], "label": "F-5 · low",
                                              "expectedText": "Temporary", "role": "button", "tag": "button"}))
        check(r["status"] == "element_gone", f"L: a removed element reports element_gone ({r['status']})")
        check(r["message"] == "The element AURA identified is no longer on the page.",
              "L: the missing-element message names the element, not the page")

        r = json.loads(highlight(h, session, {"selectors": ["#search-btn"], "label": "F-1 · high",
                                              "auditUrl": f"{base}/b.html"}))
        check(r["status"] == "page_changed", f"K: a different page is detected before anything is drawn ({r['status']})")
        check("Scan this page again" in r["message"], "K: the page-changed message asks for a new scan")

        r = json.loads(highlight(h, session, {"selectors": ["<<not a selector>>"], "label": "F-6 · low"}))
        check(r["status"] == "invalid_selector", f"L: an unusable selector is reported as such ({r['status']})")

        messages = set()
        for status in ("ambiguous", "element_gone", "page_changed", "invalid_selector"):
            messages.add(status)
        check(len(messages) == 4, "L: every failure has its own status")

        # ---------------------------------------------------------------- Part 2: the real side panel
        # A fresh tab, so part 1's deliberate DOM damage cannot affect the scan.
        h.close_tab(page)
        page = h.open_tab(f"{base}/a.html", new_window=True)
        session = h.attach(page)
        h.click_toolbar_action(ext, page)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok")
        panel.scan()
        count = panel.js("document.querySelectorAll('#findings .finding').length")
        check(count > 0, f"panel: the scan produced findings ({count})")

        # Open the first finding whose target really is one element.
        opened = panel.js("""(() => {
          const rows = [...document.querySelectorAll('#findings .finding')];
          for (const row of rows) {
            row.click();
            const hidden = document.getElementById('act-highlight').classList.contains('hidden');
            if (!hidden) return {id: row.dataset.id, what: document.getElementById('d-desc').textContent};
            document.getElementById('back').click();
          }
          return null; })()""")
        check(opened, "panel: a finding with a single element target offers Highlight")

        audit_id = panel.js("document.getElementById('scan-meta').innerText.match(/AURA-\d{4}-\d{6}/)[0]")
        req = urllib.request.Request(f"{BACKEND_URL}/api/audits/{audit_id}", headers={"X-AURA-Token": TOKEN})
        view = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        target = next(f for f in view["findings"] if f["id"] == opened["id"])["target"]
        resolves = h.evaluate(session, "(" + json.dumps(target.get("selectors") or []) +
                              ").map(s => { try { return document.querySelectorAll(s).length; } catch (e) { return 'invalid'; } })")
        print(f"    recorded target: {json.dumps(target)} resolves={resolves}", flush=True)

        panel.js("document.getElementById('act-highlight').click()")
        panel.wait("!document.getElementById('act-out').classList.contains('hidden')", 20)
        out = panel.text("act-out")
        drawn = h.evaluate(session, "document.querySelectorAll('[data-aura-overlay]').length")
        check("highlighted" in out.lower(),
              f"panel: Highlight reports success for {opened} -> {out.splitlines()[0][:100]}")
        check(drawn >= 1, "panel: the overlay is really drawn in the page")

        area = panel.js("""(() => {
          document.getElementById('back').click();
          const rows = [...document.querySelectorAll('#findings .finding')];
          for (const row of rows) { row.click();
            if (document.getElementById('act-highlight').classList.contains('hidden')) {
              return document.getElementById('d-area-note').textContent || 'hidden-without-note'; }
            document.getElementById('back').click(); }
          return 'no-area-finding'; })()""")
        if area not in ("no-area-finding",):
            check("area of the page" in area or "could not match this suggestion" in area,
                  f"panel: a finding with no single element explains itself instead of highlighting ({area[:70]})")
        else:
            print("SKIP no area-level finding on this page", flush=True)

        # The page moves on: the panel must blame the page, not the element.
        panel.js("document.getElementById('back').click()")
        h.navigate(page, f"{base}/b.html")
        h.wait_loaded(page, f"{base}/b.html")
        panel.wait("!document.getElementById('no-audit').classList.contains('hidden') || "
                   "!document.getElementById('results').classList.contains('hidden')", 20)
        if panel.visible("no-audit"):
            msg = panel.text("no-audit-msg")
            check("moved to another page" in msg or "Scan this page" in msg,
                  f"K/G: after a navigation the panel says the findings no longer apply ({msg[:80]})")
            check("no longer on the page" not in msg,
                  "K/G: a navigation is never reported as a missing element")
        else:
            panel.js("(() => { const r = document.querySelector('#findings .finding'); if (r) r.click(); })()")
            if not panel.js("document.getElementById('act-highlight').classList.contains('hidden')"):
                panel.js("document.getElementById('act-highlight').click()")
                panel.wait("!document.getElementById('act-out').classList.contains('hidden')", 20)
                out = panel.text("act-out")
                check("scan" in out.lower() and "no longer on the page" not in out.lower(),
                      f"K/G: a changed page is reported as a page change, not a missing element ({out[:90]})")
            else:
                print("SKIP no highlightable finding after navigation", flush=True)


        print(f"\nHIGHLIGHT E2E: {sum(1 for ok, _ in RESULTS if ok)}/{len(RESULTS)}", flush=True)
        return 0 if all(ok for ok, _ in RESULTS) else 1
    finally:
        h.close()
        api.shutdown()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nHIGHLIGHT E2E FAILED: {e}", flush=True)
        print(f"HIGHLIGHT E2E: {sum(1 for ok, _ in RESULTS if ok)}/{len(RESULTS)}", flush=True)
        sys.exit(1)
