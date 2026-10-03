"""
Does AURA work in Microsoft Edge?

AURA is published to both the Chrome Web Store and Microsoft Edge Add-ons from the same package, so
"it works in Edge" has to be a thing that is checked rather than a thing that was once true. Edge is
Chromium, so the same CDP harness drives it: this loads the real unpacked extension in the real Edge and
runs a scan, against a local API and the stand-in provider, so it costs nothing and needs no key.

What it checks is what would actually break the port:

  * the extension loads at all, and its pages are served from a chrome-extension:// origin - the
    assumption aura/api/security.origin_allowed() rests on. If Edge ever used a different scheme, every
    request from an Edge install would be refused with ORIGIN_NOT_ALLOWED and nothing would say why.
  * the Chrome extension APIs AURA uses all exist, sidePanel above all: the whole interface is a side
    panel, and that API is not in the original MV3 specification.
  * the panel opens, gets access to the tab from a real toolbar click, and completes a scan.

Skips, loudly, on a machine without Edge.

Run: .venv/Scripts/python.exe tests/extension_edge_e2e.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("AURA_PERSIST", "0")

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/microsoft-edge",
]

CHECKS = []


def check(ok, msg):
    CHECKS.append((bool(ok), msg))
    print(("PASS  " if ok else "FAIL  ") + msg, flush=True)


def find_edge():
    for path in EDGE_PATHS:
        if Path(path).is_file():
            return path
    return os.environ.get("AURA_EDGE_PATH") if Path(os.environ.get("AURA_EDGE_PATH", "")).is_file() else None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    edge = find_edge()
    if not edge:
        print("SKIPPED: Microsoft Edge is not installed here.")
        print("         Set AURA_EDGE_PATH to its executable to run this check on another machine.")
        return 0

    import cdp_harness
    cdp_harness._EXECUTABLE = edge          # drive Edge rather than Playwright's Chromium
    from cdp_harness import ChromeHarness, SidePanel
    import extension_browser_ai_e2e as e2e

    print(f"driving {edge}\n")
    url = e2e.serve_page()
    api = e2e.start_api()
    h = ChromeHarness(headless=True)
    try:
        product = str(h.send("Browser.getVersion").get("product", ""))
        check("Edg" in product, f"this is Edge, not Chromium ({product})")

        ext = h.load_extension(str(ROOT / "extension"))
        check(bool(ext), f"Edge loaded the unpacked extension ({ext})")

        page = h.extension_page(ext)
        origin = h.evaluate(page, "location.origin")
        check(origin.startswith("chrome-extension://"), (
            f"the extension's pages are served from chrome-extension:// ({origin}). The AURA server's "
            f"origin check accepts that scheme and no other, so a change here refuses every Edge install."))

        apis = h.evaluate(page, """(() => ({
            sidePanel: typeof chrome.sidePanel, scripting: typeof chrome.scripting,
            storage: typeof chrome.storage, action: typeof chrome.action,
            tabs: typeof chrome.tabs, runtime: typeof chrome.runtime }))()""")
        missing = sorted(name for name, kind in apis.items() if kind != "object")
        check(not missing, f"every Chrome extension API AURA uses exists in Edge (missing: {missing or 'none'})")

        h.evaluate(page, "chrome.storage.local.set(" + json.dumps(
            {"backendUrl": e2e.BACKEND, "token": e2e.TOKEN}) + ")")
        tab = h.open_tab(url, new_window=True)
        h.click_toolbar_action(ext, tab)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok", 30)
        check(True, "a toolbar click opened the side panel and granted access to that tab")

        # The stand-in provider, so this costs nothing: the live version is
        # live_provider_check.py, which spends real tokens on purpose.
        h.evaluate(panel.session, e2e.INSTRUMENT % {
            "backend": e2e.BACKEND, "token": e2e.TOKEN, "key": e2e.TEST_KEY})
        h.activate(tab)
        panel.scan(timeout=300)
        findings = panel.js("document.querySelectorAll('#findings .finding').length")
        check(findings > 0, f"a scan completed in Edge and produced findings ({findings})")

        steps = panel.js("document.getElementById('steps').textContent")
        check("straight from this browser" in steps,
              "the AI call was made in Edge itself, as it is in Chrome")
    except Exception as e:
        check(False, f"{type(e).__name__}: {str(e)[:220]}")
    finally:
        h.close()
        api.should_exit = True
        time.sleep(0.4)

    failed = [m for ok, m in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    for m in failed:
        print("  FAILED: " + m)
    print("EDGE E2E:", "PASSED" if not failed else "FAILED")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
