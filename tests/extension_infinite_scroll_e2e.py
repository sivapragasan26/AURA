"""
Does the full-page capture stop at the main content on a page that loads as you scroll?

    python tests/extension_infinite_scroll_e2e.py

Serves a local page whose feed grows every time you near the bottom — the YouTube behaviour, without
needing YouTube — and checks that the scan finishes quickly, keeps the page usable, and stops the capture
instead of chasing the feed forever.
"""
import http.server
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(r"C:\Users\somanathan\Desktop\Final_year")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdp_harness import ChromeHarness, SidePanel  # noqa: E402
from extension_e2e import BACKEND_URL, TOKEN, start_api  # noqa: E402

EXT = str(ROOT / "extension")
PORT = 8793

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Endless feed</title>
<style>
 body{margin:0;font:16px system-ui} header{position:sticky;top:0;background:#222;color:#fff;padding:12px}
 main{padding:12px} .card{height:260px;margin:10px 0;background:#eef;border:1px solid #99c;padding:10px}
 footer{padding:40px;background:#333;color:#fff}
</style></head>
<body>
  <header><button>Menu</button> Endless feed</header>
  <main id="feed">
    <h1>Today</h1>
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="60" height="60">
    <a href="#">unlabelled</a>
  </main>
  <footer>footer</footer>
<script>
  const feed = document.getElementById('feed');
  let n = 0;
  function grow(k) { for (let i = 0; i < k; i++) { const d = document.createElement('div');
    d.className = 'card'; d.textContent = 'Card ' + (++n); feed.appendChild(d); } }
  grow(6);
  // Every scroll near the bottom appends more, forever: the page has no end.
  addEventListener('scroll', () => {
    if (window.scrollY + window.innerHeight > document.body.scrollHeight - 600) grow(6);
  }, { passive: true });
  window.__growth = () => n;
</script>
</body></html>
"""


def serve():
    root = Path(tempfile.mkdtemp(prefix="aura-feed-"))
    (root / "feed.html").write_text(PAGE, encoding="utf-8")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = S(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{PORT}/feed.html"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    url = serve()
    api = start_api()
    h = ChromeHarness(headless=True)
    ok = True
    try:
        ext = h.load_extension(EXT)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")
        tab = h.open_tab(url, new_window=True)
        session = h.attach(tab)
        h.click_toolbar_action(ext, tab)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok")

        before = h.evaluate(session, "({cards: window.__growth(), height: document.body.scrollHeight, y: window.scrollY})")
        started = time.time()
        panel.scan(timeout=240)
        elapsed = time.time() - started
        after = h.evaluate(session, "({cards: window.__growth(), height: document.body.scrollHeight, y: window.scrollY})")

        steps = panel.js("document.getElementById('steps').textContent")
        capture_step = steps[steps.index("Capturing the whole page"):] if "Capturing the whole page" in steps else ""
        findings = panel.js("document.querySelectorAll('#findings .finding').length")

        print(f"\nscan finished in {elapsed:.1f}s with {findings} findings")
        print(f"page before: {before}")
        print(f"page after : {after}")
        print(f"capture step: ...{capture_step.strip()[:160]}")

        checks = [
            (elapsed < 120, f"the scan finished rather than stalling ({elapsed:.1f}s)"),
            (findings > 0, f"the scan produced findings ({findings})"),
            (after["y"] == before["y"], f"the reader's scroll position was put back ({after['y']})"),
            ("keeps loading" in capture_step or "main content" in capture_step or "time limit" in capture_step,
             "the capture reports why it stopped"),
            (after["cards"] < before["cards"] + 200, f"the capture did not chase the feed forever "
                                                     f"({before['cards']} -> {after['cards']} cards)"),
        ]
        for good, msg in checks:
            print(("PASS " if good else "FAIL ") + msg)
            ok = ok and good

    finally:
        h.close()
        api.shutdown()
    print("\nINFINITE SCROLL CHECK:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
