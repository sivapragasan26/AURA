"""
Optional live check of the reported Flipkart scenario (needs internet; not part of the automated suite):

    python tests/extension_flipkart_check.py

Scans https://www.flipkart.com in Tab A (Mock provider, local test server), opens Flipkart in a second tab
(like a product opened in a new tab), activates it, switches back to Tab A, and verifies the panel never shows
"belong to another tab" while Tab A's findings are displayed on Tab A.
"""
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdp_harness import ChromeHarness, SidePanel  # noqa: E402
from extension_e2e import BACKEND_URL, TOKEN, start_api  # noqa: E402
from extension_tabsync_e2e import ANOTHER_TAB, settle  # noqa: E402

SITE = "https://www.flipkart.com/"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(420, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    api = start_api()
    h = ChromeHarness()
    ok = False
    try:
        ext = h.load_extension(str(ROOT / "extension"))
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")
        a = h.open_tab(SITE, new_window=True)
        h.click_toolbar_action(ext, a)
        panel = SidePanel(h, ext)
        panel.wait("document.getElementById('conn').textContent.includes('Mock')")
        panel.scan(timeout=240)
        u = settle(panel, lambda u: u["results"], "scan")
        print(f"Tab A (Flipkart) scanned: host={u['host']} findings={u['findings']}")
        b = h.open_tab(SITE + "?aura_second_tab=1", wait=False)
        h.activate(b)
        h.wait_loaded(b, SITE, timeout=60)
        h.click_toolbar_action(ext, b)
        u = settle(panel, lambda u: u["host"] == "www.flipkart.com" and not u["results"], "tab B")
        print(f"Tab B (Flipkart, not scanned): results shown={u['results']} card='{u['noAuditText'][:70]}…'")
        h.activate(a)
        u = settle(panel, lambda u: u["results"], "back to A")
        bad = ANOTHER_TAB in u["visibleText"]
        print(f"Back on Tab A: host={u['host']} findings={u['findings']} 'another tab' message shown={bad}")
        ok = u["host"] == "www.flipkart.com" and u["findings"] > 0 and not bad
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        api.should_exit = True
        print("FLIPKART CHECK:", "PASSED" if ok else "FAILED", flush=True)
        os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
