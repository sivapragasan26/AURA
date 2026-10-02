"""
Real-browser regression test for the activeTab -> side panel access lifecycle.

    python tests/extension_activation_e2e.py

The extension is loaded UNMODIFIED (no test-only host permissions): page access exists only through the
activeTab grant of a real toolbar-action click, performed with CDP `Extensions.triggerAction` (same code
path as a user's click). The real side panel is driven through its DOM.

Checks: A-J of the manual test plan, plus tab switching, per-tab activation, new tabs, reload, cross-origin
navigation, tab close cleanup, and extension reload.
"""
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import uvicorn  # noqa: E402

from aura.api.server import create_app  # noqa: E402
from aura.config import settings  # noqa: E402
from cdp_harness import LAB_PORT, serve_test_lab, ChromeHarness, SidePanel, start_cross_origin_lab  # noqa: E402  (direct CDP pipe, no Playwright client)

TOKEN = "act-" + "y" * 36
LAB = f"http://127.0.0.1:{LAB_PORT}"  # served by cdp_harness.serve_test_lab()
EXT = str(ROOT / "extension")
RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise AssertionError(msg)


def port_in_use(host: str, port: int) -> bool:
    import socket
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


# If the user's own AURA server already listens on 127.0.0.1:8765, never touch it: run the test server on the
# IPv6 loopback instead and point the extension at http://localhost:8765 (also covered by the manifest).
API_HOST = "::1" if port_in_use("127.0.0.1", 8765) else "127.0.0.1"
BACKEND_URL = "http://localhost:8765" if API_HOST == "::1" else "http://127.0.0.1:8765"


def start_api():
    settings.AI_PROVIDER = "mock"
    server = uvicorn.Server(uvicorn.Config(create_app(token=TOKEN), host=API_HOST, port=8765, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError("API did not start")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(300, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    serve_test_lab()
    api = start_api()
    h = ChromeHarness()
    try:
        ext_id = h.load_extension(EXT)
        check(True, f"extension loaded unmodified (id {ext_id}); no host permission for any web page")
        # Harness note: in a DevTools-launched Chromium the service worker started at install time does not
        # run until an extension page starts a fresh instance (not a user-facing behaviour). Opening AURA's
        # settings page does that and is also where the pairing token is configured.
        settings_page = h.extension_page(ext_id)
        h.evaluate(settings_page, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")

        # X: a first page, activated so the real side panel opens
        tab_x = h.open_tab(f"{LAB}/02_ui_ux_suite/", new_window=True)
        time.sleep(1.0)
        h.click_toolbar_action(ext_id, tab_x)
        panel = SidePanel(h, ext_id)
        check(True, "toolbar click opened the real side panel")
        sw = settings_page  # extension-page context: same chrome.* APIs as the service worker
        panel.wait("document.getElementById('conn').textContent.includes('Mock')", 15)
        check(True, f"panel paired with the test server ({BACKEND_URL}, Mock provider)")
        behaviour = h.evaluate(sw, "chrome.sidePanel.getPanelBehavior()")
        check(behaviour == {"openPanelOnActionClick": False}, f"openPanelOnActionClick is off so onClicked fires: {behaviour}")
        st = panel.wait_access("access-ok")
        check(not st["scanDisabled"], f"tab X activated by its toolbar click ({st['host']})")

        # A/B/C: a normal page in a new tab, panel open, not activated yet
        tab_a = h.open_tab(f"{LAB}/01_accessibility_suite/")
        time.sleep(1.0)
        h.activate(tab_a)
        st = panel.wait_access("access-needed")
        check(st["scanDisabled"] and "Click the AURA icon" in st["text"], "A-C: new tab A is NOT activated; Scan is disabled")
        probe_before = h.evaluate(sw, """(async () => { const [t] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
            try { await chrome.scripting.executeScript({target: {tabId: t.id}, func: () => 1}); return 'ACCESS'; } catch (e) { return 'NO ACCESS'; } })()""")
        check(probe_before == "NO ACCESS", "A-C: AURA really has no access to tab A before the click")

        # D/E/F: toolbar click on A -> panel updates without reopening
        h.click_toolbar_action(ext_id, tab_a)
        st = panel.wait_access("access-ok")
        check(not st["scanDisabled"] and f"127.0.0.1:{LAB_PORT}" in st["host"], f"D-F: after the toolbar click tab A is available: '{st['text'][:40]}…'")

        # G-J: scan
        panel.js("document.getElementById('scan').click()")
        panel.wait("!document.getElementById('progress').classList.contains('hidden') || !document.getElementById('results').classList.contains('hidden')", 10)
        check(True, "G-H: Scan Current Page started evidence collection")
        panel.wait("!document.getElementById('results').classList.contains('hidden') || !document.getElementById('error').classList.contains('hidden')", 120)
        err = panel.js("document.getElementById('error').classList.contains('hidden') ? '' : document.getElementById('error').textContent")
        check(not err, f"I: scan completed without error {err[:200]}")
        n = panel.js("document.querySelectorAll('#findings .finding').length")
        banner = panel.js("document.getElementById('state-banner').textContent")
        check(n > 0 and "Scan complete" in banner, f"J: {n} findings shown ({banner[:40]}…)")

        # Tab switching preserves per-tab state
        h.activate(tab_x)
        panel.wait_access("access-ok")
        check(True, "switching to tab X: still activated (its own activation preserved)")
        h.activate(tab_a)
        panel.wait_access("access-ok")
        check(True, "switching back to tab A: still activated")

        # A new tab does not inherit activation
        tab_y = h.open_tab(f"{LAB}/03_navigation_interaction_suite/")
        time.sleep(1.0)
        h.activate(tab_y)
        panel.wait_access("access-needed")
        check(True, "new tab Y does not inherit any activation")

        # Reload keeps the grant (same origin) per Chrome's activeTab lifecycle
        h.activate(tab_a)
        panel.wait_access("access-ok")
        h.reload(tab_a)
        st = panel.wait_access("access-ok")
        check(True, "reloading tab A (same origin): access kept, as Chrome's activeTab lifecycle specifies")

        # Navigation to another origin revokes the grant
        h.navigate(tab_a, f"{start_cross_origin_lab()}/01_accessibility_suite/")
        st = panel.wait_access("access-needed")
        panel.wait("document.getElementById('access').textContent.includes('Access to this tab ended')")
        st = panel.access()
        check(st["scanDisabled"], f"navigating tab A to another origin revokes access, panel says so: '{st['text'][:60]}…'")
        h.click_toolbar_action(ext_id, tab_a)
        panel.wait_access("access-ok")
        check(True, "clicking the toolbar icon on the new origin re-activates tab A")

        # Closing a tab clears its activation state
        ids_before = h.evaluate(sw, "chrome.storage.session.get('aura.activatedTabs').then(r => Object.keys(r['aura.activatedTabs'] || {}).length)")
        h.close_tab(tab_x)
        time.sleep(1.0)
        ids_after = h.evaluate(sw, "chrome.storage.session.get('aura.activatedTabs').then(r => Object.keys(r['aura.activatedTabs'] || {}).length)")
        check(ids_after == ids_before - 1, f"closing tab X removed its activation record ({ids_before} -> {ids_after})")
        stored = h.evaluate(sw, "chrome.storage.session.get('aura.activatedTabs').then(r => JSON.stringify(r))")
        check("?" not in stored and "dashboard" not in stored and "01_accessibility" not in stored,
              f"activation state holds only tab id / origin / time: {stored[:120]}")

        # Extension reload resets activation (session storage and activeTab grants are dropped)
        reloaded_id = h.load_extension(EXT)  # same as "Reload" in chrome://extensions for an unpacked extension
        check(reloaded_id == ext_id, "extension reloaded (same id)")
        time.sleep(1.0)
        sw = h.extension_page(ext_id)
        after_reload = h.evaluate(sw, "chrome.storage.session.get('aura.activatedTabs').then(r => r['aura.activatedTabs'] || null)")
        probe = h.evaluate(sw, """(async () => { const tabs = await chrome.tabs.query({}); const out = [];
            for (const t of tabs) { if ((t.url || '').startsWith('chrome-extension://')) continue;
              try { await chrome.scripting.executeScript({target: {tabId: t.id}, func: () => 1}); out.push('ACCESS'); }
              catch (e) { out.push('NO ACCESS'); } } return out; })()""")
        check(after_reload is None and "ACCESS" not in probe, f"extension reload: activation state cleared and no tab accessible ({probe})")
        h.activate(tab_a)
        h.click_toolbar_action(ext_id, tab_a)
        panel = SidePanel(h, ext_id)
        panel.wait_access("access-ok")
        check(True, "after reload, a new toolbar click re-activates the tab and reopens the panel")
    except Exception as e:
        import traceback
        traceback.print_exc()
        RESULTS.append((False, f"aborted: {e}"))
    finally:
        api.should_exit = True
        passed = sum(1 for ok, _ in RESULTS if ok)
        print(f"\nACTIVATION E2E: {passed}/{len(RESULTS)} checks passed", flush=True)
        failed = any(not ok for ok, _ in RESULTS)
        os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        os._exit(1)
