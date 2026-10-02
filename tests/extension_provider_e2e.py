"""
Real-browser check of provider selection in the side panel.

    python tests/extension_provider_e2e.py

Covers: the provider list, switching provider, a provider with no API key (NOT CONFIGURED), that a scan with an
unusable provider degrades to deterministic-only instead of silently using Mock AI, that Mock AI is always
labelled as a demo, and that Ask AURA explains what to select. No API key is needed and no AI request is made.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from cdp_harness import ChromeHarness, SidePanel, serve_test_lab  # noqa: E402
from extension_e2e import BACKEND_URL, LAB, TOKEN, start_api  # noqa: E402

EXT = str(ROOT / "extension")
RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise AssertionError(msg)


def select_provider(panel, provider):
    if not panel.visible("provider-card"):
        panel.js("document.getElementById('provider-toggle').click()")
    panel.wait("!document.getElementById('provider-card').classList.contains('hidden')")
    panel.wait("document.getElementById('provider-select').options.length > 1")
    panel.js("(() => { const s = document.getElementById('provider-select');"
             f" s.value = '{provider}'; s.dispatchEvent(new Event('change')); }})()")
    panel.js("document.getElementById('provider-save').click()")
    panel.wait("document.getElementById('provider-status').textContent.includes('Saved')", 20)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    threading.Timer(600, lambda: (print("FAIL global timeout", flush=True), os._exit(3))).start()
    serve_test_lab()
    api = start_api()
    h = ChromeHarness()
    try:
        ext = h.load_extension(EXT)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")
        lab = h.open_tab(f"{LAB}/01_accessibility_suite/", new_window=True)
        h.click_toolbar_action(ext, lab)
        panel = SidePanel(h, ext)
        panel.wait("document.getElementById('conn').textContent.includes('Mock')")

        # Mock AI is always labelled as a demo
        check("Mock AI · Demo" in panel.text("conn") and "Mock AI · Demo" in panel.text("ai-provider"),
              f"Mock AI is labelled as a demo: '{panel.text('conn')}'")

        # The five providers are offered
        panel.js("document.getElementById('provider-toggle').click()")
        panel.wait("document.getElementById('provider-select').options.length > 1")
        options = panel.js("Array.from(document.getElementById('provider-select').options).map(o => o.value + ':' + o.text)")
        check([o.split(":")[0] for o in options] == ["mock", "groq", "gemini", "openai", "anthropic"],
              "provider selector lists Mock, Groq, Gemini, OpenAI, Anthropic: " + ", ".join(options))

        # Switching to a provider with no key: clearly reported, never silently replaced by Mock.
        # Which provider that is depends on the machine: a key may be configured on the AURA server for
        # any of them, so the unconfigured one is discovered rather than assumed.
        providers = panel.js("""(async () => {
            const s = await chrome.storage.local.get({backendUrl: '', token: ''});
            const r = await fetch(s.backendUrl + '/api/providers', {headers: {'X-AURA-Token': s.token}});
            return JSON.stringify((await r.json()).providers);
        })()""")
        providers = json.loads(providers)
        unconfigured = next((p for p in providers if not p["is_mock"] and not p["key_configured"]), None)
        check(unconfigured is not None,
              "at least one provider has no API key on this machine, so the no-key path can be exercised: "
              + ", ".join(f"{p['provider']}={p['key_configured']}" for p in providers))
        label = unconfigured["label"]
        select_provider(panel, unconfigured["provider"])
        panel.wait(f"document.getElementById('ai-provider').textContent.includes({json.dumps(label)})")
        check(label in panel.text("ai-provider") and "Mock" not in panel.text("ai-provider"),
              f"provider switched to {label}: '{panel.text('ai-provider')}'")
        check("no key" in panel.text("conn").lower(), f"missing API key is visible in the status: '{panel.text('conn')}'")
        panel.js("document.getElementById('provider-test').click()")
        panel.wait("document.getElementById('provider-status').textContent.includes('NOT CONFIGURED')", 30)
        check(True, "Test connection reports NOT CONFIGURED: " + panel.text("provider-status")[:70])
        panel.js("document.getElementById('provider-close').click()")

        # A scan with an unusable provider: deterministic-only, and it says so
        panel.scan()
        banner = panel.text("state-banner")
        check("Deterministic-only" in banner and "unavailable" in banner.lower(),
              "scan with an unusable provider is deterministic-only, not silently Mock: " + banner.splitlines()[0])
        check(label not in banner or "Mock" not in banner, "the failed provider is not swapped for Mock AI")
        meta = panel.js("Array.from(document.querySelectorAll('#scan-meta li')).map(l => l.textContent).join(' | ')")
        ai_line = next((l for l in meta.split(" | ") if l.startswith("AI:")), meta[:80])
        check(unconfigured["provider"] in meta.lower(), "the audit records the provider it ran with: " + ai_line)
        scores = panel.text("scores")
        check("Not evaluated" in scores, "UI and UX are not evaluated without AI: " + scores.replace("\n", " "))

        # Ask AURA explains what to select
        panel.js("document.querySelectorAll('#findings .finding')[0].click()")
        panel.wait("!document.getElementById('detail').classList.contains('hidden')")
        panel.js("document.getElementById('ask-input').value = 'why?'; document.querySelector('#ask-form button').click()")
        panel.wait("document.querySelector('#ask-log .msg.aura') && !document.querySelector('#ask-log .msg.aura').innerText.includes('Thinking')", 30)
        ask = panel.js("Array.from(document.querySelectorAll('#ask-log .msg')).map(m => m.className + ':' + m.textContent).join(' || ')")
        check("unavailable" in ask.lower() or "not configured" in ask.lower(),
              "Ask AURA with an unusable provider says so instead of answering: " + ask[-110:])

        # Back to Mock AI: the next scan uses it, previous audits keep their own provider
        select_provider(panel, "mock")
        try:
            panel.wait("document.getElementById('conn').textContent.includes('Mock')", 25)
        except AssertionError:
            print("DEBUG conn:", panel.text("conn"), "| ai:", panel.text("ai-provider"),
                  "| status:", panel.text("provider-status"), flush=True)
            raise
        check("Mock AI · Demo" in panel.text("ai-provider"), "switched back to Mock AI · Demo")
        old_meta = panel.js("Array.from(document.querySelectorAll('#scan-meta li')).map(l => l.textContent).join(' | ')")
        check(unconfigured["provider"] in old_meta.lower(),
              f"the earlier audit still records {label}: changing provider did not rewrite it")
        panel.scan()
        meta = panel.js("Array.from(document.querySelectorAll('#scan-meta li')).map(l => l.textContent).join(' | ')")
        check("mock" in meta.lower(), "the new scan records Mock AI")

        # Ask AURA on Mock AI names the providers to choose
        panel.js("document.querySelectorAll('#findings .finding')[0].click()")
        panel.wait("!document.getElementById('detail').classList.contains('hidden')")
        panel.js("document.getElementById('ask-input').value = 'why?'; document.querySelector('#ask-form button').click()")
        panel.wait("document.querySelector('#ask-log .msg.aura') && "
                   "!document.querySelector('#ask-log .msg.aura').textContent.includes('Thinking')", 30)
        ask = panel.js("Array.from(document.querySelectorAll('#ask-log .msg.aura')).map(m => m.textContent).join(' ')")
        check("requires a real AI provider" in ask and "Groq" in ask,
              "Ask AURA on Mock AI names the providers to select: " + ask[:110])
    except Exception as e:
        import traceback
        traceback.print_exc()
        RESULTS.append((False, f"aborted: {e}"))
    finally:
        api.should_exit = True
        passed = sum(1 for ok, _ in RESULTS if ok)
        print(f"\nPROVIDER E2E: {passed}/{len(RESULTS)} checks passed", flush=True)
        os._exit(0 if RESULTS and all(ok for ok, _ in RESULTS) else 1)


if __name__ == "__main__":
    main()
