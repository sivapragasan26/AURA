"""
End-to-end run of the REAL, UNMODIFIED extension in Chromium (manual/CI driver, not collected by pytest):

    python tests/extension_e2e.py [suite_name] [--interact] [--screens OUT_DIR]

Loads extension/ exactly as shipped (no test-only permissions), opens a Test Lab page, clicks the AURA toolbar
action for real (CDP Extensions.triggerAction: the same path as a user click, granting activeTab), and drives
the real side panel: scan -> results -> finding -> highlight / explain -> Ask AURA ->
close panel (all page marks removed). The AURA API runs in-process with the Mock provider.

See tests/extension_activation_e2e.py for the activation lifecycle (tab switching, reload, navigation, …).
"""
import os
import socket
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
from cdp_harness import LAB_PORT, ChromeHarness, SidePanel, serve_test_lab  # noqa: E402

TOKEN = "e2e-" + "x" * 36
LAB = f"http://127.0.0.1:{LAB_PORT}"  # served by cdp_harness.serve_test_lab()
EXT = str(ROOT / "extension")


def port_in_use(host: str, port: int) -> bool:
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


# Never touch a user's own AURA server on 127.0.0.1:8765: use the IPv6 loopback (localhost:8765) instead.
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


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise AssertionError(msg)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(420, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    suite = next((a for a in sys.argv[1:] if not a.startswith("--") and not Path(a).suffix and "\\" not in a and "/" not in a),
                 "05_mixed_realistic_suite")
    screens = Path(sys.argv[sys.argv.index("--screens") + 1]) if "--screens" in sys.argv else None
    serve_test_lab()
    api = start_api()
    h = ChromeHarness()
    ok = False
    try:
        ext_id = h.load_extension(EXT)
        check(bool(ext_id), f"extension loaded unmodified (id {ext_id})")
        settings_page = h.extension_page(ext_id)  # configure pairing (also starts the service worker)
        h.evaluate(settings_page, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")

        lab = h.open_tab(f"{LAB}/{suite}/", new_window=True)
        lab_s = h.attach(lab)
        h.click_toolbar_action(ext_id, lab)
        panel = SidePanel(h, ext_id)
        panel.wait("document.getElementById('conn').textContent.includes('Connected')")
        check(True, "toolbar click opened the side panel, paired: " + panel.text("conn"))
        st = panel.wait_access("access-ok")
        check(not st["scanDisabled"], "current tab activated by the toolbar click")

        if "--interact" in sys.argv:
            panel.click("#opt-interact")
        panel.click("#scan")
        panel.wait("!document.getElementById('results').classList.contains('hidden') || "
                   "!document.getElementById('error').classList.contains('hidden')", 180)
        if panel.visible("error"):
            raise AssertionError("scan failed: " + panel.text("error"))
        banner = panel.text("state-banner")
        check("Scan complete" in banner, "scan completed: " + banner.splitlines()[0])
        scores = (panel.text("score-aura") + " " + panel.text("scores").replace("\n", " ")).upper()
        check(any(ch.isdigit() for ch in scores) and "RUNTIME" in scores and ("A11Y" in scores or "ACCESSIBILITY" in scores), "scores shown: " + scores)
        n_findings = panel.js("document.querySelectorAll('#findings .finding').length")
        check(n_findings > 0, f"{n_findings} findings listed")
        sev = panel.text("sev-row").replace("\n", " ").lower()
        check(all(s in sev for s in ("critical", "high", "medium", "low")), "severity counts shown: " + sev)
        coverage = panel.js("Array.from(document.querySelectorAll('#coverage li')).map(l => l.className + ':' + l.textContent).join('\\n')")
        if "--interact" in sys.argv:
            steps = panel.js("document.getElementById('steps').textContent")
            check("Safe interaction test" in steps and "clicked" in steps,
                  "safe interaction test ran: " + steps[steps.index("Safe interaction test"):][:90])
            check("yes:Controlled Interaction" in coverage, "interaction evidence reached the engine (coverage)")
        if screens:
            screens.mkdir(parents=True, exist_ok=True)
            panel.screenshot(str(screens / "1_results.png"))

        rules = panel.js("Array.from(document.querySelectorAll('#findings .finding')).map(b => b.dataset.rule)")
        # Pick a finding that really has one element behind it, by asking the panel whether it offers
        # Highlight. Matching on the wording of the location text broke whenever that wording improved.
        elem_idx = panel.js("""
            (() => {
                const buttons = Array.from(document.querySelectorAll('#findings .finding'));
                for (let i = 0; i < buttons.length; i++) {
                    buttons[i].click();
                    const offered = !document.getElementById('act-highlight').classList.contains('hidden');
                    document.getElementById('back').click();
                    if (offered) return i;
                }
                return 0;
            })()
        """)
        panel.js(f"document.querySelectorAll('#findings .finding')[{elem_idx}].click()")
        check(panel.visible("detail"), "finding detail opened: " + panel.text("d-title"))
        check(bool(panel.text("d-desc").strip()),
              "the card states the problem: " + panel.text("d-desc")[:70])
        check(not panel.js("document.getElementById('tech-details').open"), "technical details start collapsed")
        check("selector" not in panel.text("d-title").lower() and "#" not in panel.text("d-title"),
              "no raw selector in the finding title: " + panel.text("d-title"))
        panel.js("document.querySelector('#tech-details summary').click()")
        facts = panel.text("d-facts").upper()
        check("VERIFICATION" in facts and "EVIDENCE" in facts and "AI CONTRIBUTION" in facts and "RULE" in facts,
              "expanded technical details show rule, verification, evidence and AI contribution")

        panel.click("#act-highlight")
        panel.wait("!document.getElementById('act-out').classList.contains('hidden')")
        out = panel.text("act-out")
        has_overlay = h.evaluate(lab_s, "!!document.querySelector('[data-aura-overlay]')")
        check("highlighted" in out.lower() and has_overlay, "Highlight Element drew an overlay on the page: " + out.splitlines()[0])

        # The card carries one short sentence; the full account is behind Explain.
        card_sentence = panel.text("d-desc").strip()
        check(card_sentence and len(card_sentence) <= 170,
              f"the card states the problem in one short sentence ({len(card_sentence)} chars)")
        check(not panel.js("!!document.getElementById('d-why')")
              and not panel.js("!!document.getElementById('d-fix')"),
              "the card no longer carries the full why/what-to-do detail")

        # Screenshot: the capture cropped to a finding, served by the local server. Pick a finding that
        # really has a region in the capture (an element below the fold was never photographed).
        shot_idx = panel.js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('#findings .finding'));
                for (let i = 0; i < rows.length; i++) {
                    rows[i].click();
                    const has = !document.getElementById('act-shot').classList.contains('hidden');
                    document.getElementById('back').click();
                    if (has) return i;
                }
                return -1;
            })()
        """)
        if shot_idx >= 0:
            panel.js(f"document.querySelectorAll('#findings .finding')[{shot_idx}].click()")
            panel.click("#act-shot")
            try:
                panel.wait("!!document.querySelector('#act-out img.shot') && "
                           "document.querySelector('#act-out img.shot').naturalWidth > 0", 30)
            except AssertionError:
                raise AssertionError("Screenshot produced no image. Panel said: "
                                     + " ".join(panel.text("act-out").split())[:200])
            dims = panel.js("(() => { const i = document.querySelector('#act-out img.shot');"
                            " return i.naturalWidth + 'x' + i.naturalHeight; })()")
            check("x" in dims and not dims.startswith("0"), "Screenshot showed the cropped capture: " + dims)
        else:
            print("SKIP no finding on this page has a region inside the capture", flush=True)

        panel.js(f"document.getElementById('back').click()")
        panel.js(f"document.querySelectorAll('#findings .finding')[{elem_idx}].click()")
        panel.click("#act-explain")
        # Explain carries the whole problem in plain language, with nothing technical in it.
        panel.wait("document.getElementById('act-out').innerText.includes('What is happening')")
        explain_text = panel.text("act-out")
        check("No new AI request" in explain_text, "Explain with AURA returned a grounded explanation")
        low = explain_text.lower()
        leaked = [t for t in ("wcag", "axe-core", "aria-", "selector", "landmark") if t in low]
        check(not leaked, f"Explain contains no technical wording (leaked: {leaked})")
        check(card_sentence.rstrip(".") in explain_text or len(explain_text) > len(card_sentence),
              "Explain says more than the card does")

        panel.click("#back")
        panel.wait("document.getElementById('results') && !document.getElementById('results').classList.contains('hidden')")
        time.sleep(0.6)
        check(not panel.js("!!document.getElementById('act-preview')"), "Preview fix button is completely removed from DOM")
        elem_click_idx = elem_idx if elem_idx >= 0 else 0
        panel.js(f"document.querySelectorAll('#findings .finding')[{elem_click_idx}].click()")

        panel.js("document.getElementById('ask-input').value = 'Can you redesign this page?'")
        panel.js("document.querySelector('#ask-form button').click()")
        panel.wait("document.querySelector('#ask-log .msg.aura') && !document.querySelector('#ask-log .msg.aura').innerText.includes('Thinking')")
        check("real AI provider" in panel.text("ask-log"), "Ask AURA with Mock provider: explicit unavailable message")

        panel.click("#act-highlight")
        time.sleep(0.5)
        panel.close()
        time.sleep(1.5)
        check(not h.evaluate(lab_s, "!!document.querySelector('[data-aura-overlay]')"), "closing the panel removed all AURA overlays")
        check(h.evaluate(lab_s, "!window.__AURA_RT__"), "runtime probe removed after the scan")
        ok = True
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        api.should_exit = True
        print("\nEXTENSION E2E: ALL CHECKS PASSED" if ok else "\nEXTENSION E2E: FAILED", flush=True)
        os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
