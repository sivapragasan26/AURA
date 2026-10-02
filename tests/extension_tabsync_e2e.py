"""
Real-browser regression test: side-panel results must always belong to the CURRENT tab's current page.

    python tests/extension_tabsync_e2e.py

Bug (fixed): the panel kept one audit and a sticky `state.stale` message. Switching to another tab set
"These results belong to another tab…"; nothing ever cleared it when the user came back, so the panel showed
the audited page's findings next to that message (the Flipkart report). It also kept showing Tab A's findings
while Tab B was active.

The extension is loaded UNMODIFIED; toolbar clicks are real (CDP Extensions.triggerAction).
"""
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdp_harness import serve_test_lab, ChromeHarness, SidePanel  # noqa: E402
from extension_e2e import BACKEND_URL, LAB, TOKEN, start_api  # noqa: E402  (same Mock-provider test server)

LAB_HOST = LAB.split("//", 1)[1]

EXT = os.environ.get("AURA_E2E_EXTENSION", str(ROOT / "extension"))  # override only to prove the test catches old builds
ANOTHER_TAB = "belong to another tab"
RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise AssertionError(msg)


def ui(panel):
    """What the user sees in the panel, as data."""
    return panel.js("""(() => {
        const vis = (id) => { const el = document.getElementById(id); return !!el && !el.classList.contains('hidden'); };
        return {
            host: document.getElementById('page-host').textContent,
            results: vis('results'), detail: vis('detail'), noAudit: vis('no-audit'),
            noAuditText: (document.getElementById('no-audit-msg') || {textContent: ''}).textContent,
            banner: vis('results') ? document.getElementById('state-banner').innerText : '',
            findings: document.querySelectorAll('#findings .finding').length,
            auditUrl: (document.querySelector('#state-banner p') || {textContent: ''}).textContent,
            visibleText: document.body.innerText,
        };
    })()""")


def settle(panel, pred, what, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = ui(panel)
        if pred(last):
            return last
        time.sleep(0.25)
    raise AssertionError(f"{what}: {last}")


def no_false_other_tab(u):
    return ANOTHER_TAB not in u["visibleText"]


def scan(panel):
    panel.scan()


def open_tab(h, url):
    t = h.open_tab(url, wait=False)
    h.activate(t)
    h.wait_loaded(t, url)
    return t


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(900, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    serve_test_lab()
    api = start_api()
    h = ChromeHarness()
    url_a = f"{LAB}/05_mixed_realistic_suite/"
    url_b = f"{LAB}/01_accessibility_suite/"
    try:
        ext = h.load_extension(EXT)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")

        # 1. Scan Tab A -> results visible
        a = h.open_tab(url_a, new_window=True)
        h.click_toolbar_action(ext, a)
        panel = SidePanel(h, ext)
        panel.wait("document.getElementById('conn').textContent.includes('Mock')")  # paired with THIS test server
        scan(panel)
        u = settle(panel, lambda u: u["results"] and u["findings"] > 0, "1")
        findings_a = u["findings"]
        check("05_mixed_realistic_suite" in u["auditUrl"] and no_false_other_tab(u), f"1. scan Tab A: {findings_a} findings for Tab A")

        # 2. Switch to Tab B -> Tab A results are not presented as Tab B's
        b = open_tab(h, url_b)
        u = settle(panel, lambda u: not u["results"] and not u["detail"], "2. Tab A results still shown on Tab B")
        check(u["noAudit"] and ANOTHER_TAB in u["noAuditText"], "2. on Tab B: Tab A's findings hidden; panel says they belong to another tab")

        # 3. Return to Tab A -> results available again, no stale "another tab" message
        h.activate(a)
        u = settle(panel, lambda u: u["results"], "3")
        check(u["findings"] == findings_a and no_false_other_tab(u) and not u["noAudit"],
              "3. back on Tab A: its results are shown and the 'another tab' message is gone")

        # 10. The Flipkart report: same site open in a second tab (e.g. a product opened in a new tab)
        c = open_tab(h, url_a + "?tab=c")  # same page (AURA ignores the query string); query only makes the CDP tab unique
        u = settle(panel, lambda u: not u["results"] and u["noAudit"], "10. second tab on the same page shows Tab A's results")
        check(u["host"] == "Current tab", "10. a second, not-activated tab on the same page: Tab A's audit not inherited (URL not readable)")
        h.click_toolbar_action(ext, c)  # user activates the second tab: its host becomes visible, like "Page: www.flipkart.com"
        u = settle(panel, lambda u: u["host"] == LAB_HOST and u["noAudit"] and not u["results"], "10. activated second tab")
        check(ANOTHER_TAB in u["noAuditText"] and u["findings"] == findings_a,
              "10. activated second tab on the same site: no inherited findings shown; told they belong to another tab")
        h.activate(a)
        u = settle(panel, lambda u: u["results"], "10")
        check(u["host"] == LAB_HOST and no_false_other_tab(u),
              "10. Flipkart scenario: back on the audited tab, host and findings match and no 'another tab' message")
        h.close_tab(c)

        # 4. Reload Tab A -> findings kept but explicitly marked stale
        h.reload(a)
        u = settle(panel, lambda u: u["results"] and "reloaded" in u["banner"], "4")
        check(no_false_other_tab(u), "4. reload: findings marked stale ('reloaded after the scan'), no 'another tab' message")
        scan(panel)
        u = settle(panel, lambda u: u["results"] and "reloaded" not in u["banner"], "4b")
        check(True, "4. re-scan after reload clears the stale note")

        # 5. Navigate Tab A to another URL -> audit invalidated, new scan required
        h.navigate(a, f"{LAB}/02_ui_ux_suite/")
        u = settle(panel, lambda u: not u["results"] and u["noAudit"], "5")
        check("moved to another page" in u["noAuditText"] and "Scan this page" in u["noAuditText"],
              "5. navigation: old findings hidden, user told to scan the new page")
        h.navigate(a, url_a)
        u = settle(panel, lambda u: not u["results"], "5b")
        check(u["findings"] == 0 or not u["results"], "5. the invalidated audit does not come back on navigating back")
        scan(panel)
        findings_a = settle(panel, lambda u: u["results"], "5c")["findings"]

        # 9. Two tabs with separate scans keep their own audits
        h.activate(b)
        h.click_toolbar_action(ext, b)
        scan(panel)
        u = settle(panel, lambda u: u["results"] and "01_accessibility_suite" in u["auditUrl"], "9")
        findings_b = u["findings"]
        h.activate(a)
        u = settle(panel, lambda u: u["results"] and "05_mixed_realistic_suite" in u["auditUrl"], "9a")
        check(u["findings"] == findings_a and no_false_other_tab(u), f"9. Tab A shows its own audit ({findings_a} findings)")
        h.activate(b)
        u = settle(panel, lambda u: u["results"] and "01_accessibility_suite" in u["auditUrl"], "9b")
        check(u["findings"] == findings_b and no_false_other_tab(u), f"9. Tab B shows its own audit ({findings_b} findings)")

        # 6. Close / reopen side panel -> the current tab's audit is restored
        h.activate(a)
        settle(panel, lambda u: "05_mixed" in u["auditUrl"], "6pre")
        panel.close()
        time.sleep(1.0)
        h.click_toolbar_action(ext, a)
        panel = SidePanel(h, ext)
        u = settle(panel, lambda u: u["results"], "6")
        check("05_mixed_realistic_suite" in u["auditUrl"] and no_false_other_tab(u),
              "6. reopened panel on Tab A: Tab A's audit restored, no stale message")

        # 7. Service-worker restart -> state still correct
        h.send("ServiceWorker.enable", {}, session=sp)
        h.send("ServiceWorker.stopAllWorkers", {}, session=sp)
        time.sleep(1.0)
        h.activate(b)
        u = settle(panel, lambda u: u["results"] and "01_accessibility_suite" in u["auditUrl"], "7")
        h.activate(a)
        u = settle(panel, lambda u: u["results"] and "05_mixed_realistic_suite" in u["auditUrl"], "7a")
        check(no_false_other_tab(u), "7. after a service-worker restart each tab still shows its own audit")

        # 8. Extension reload -> stored audit references are cleared; nothing stale is shown
        h.load_extension(EXT)
        time.sleep(1.0)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")
        h.activate(a)
        h.click_toolbar_action(ext, a)
        panel = SidePanel(h, ext)
        u = settle(panel, lambda u: not u["results"] and "No results for this page yet" in u["noAuditText"], "8")
        check(no_false_other_tab(u), "8. after extension reload: no old results, no 'another tab' message; scan required")
        scan(panel)
        u = settle(panel, lambda u: u["results"], "8b")
        check(u["findings"] > 0, "8. scan after reload works")
    except Exception as e:
        import traceback
        traceback.print_exc()
        RESULTS.append((False, f"aborted: {e}"))
    finally:
        api.should_exit = True
        passed = sum(1 for ok, _ in RESULTS if ok)
        print(f"\nTAB SYNC E2E: {passed}/{len(RESULTS)} checks passed", flush=True)
        os._exit(0 if RESULTS and all(ok for ok, _ in RESULTS) else 1)


if __name__ == "__main__":
    main()
