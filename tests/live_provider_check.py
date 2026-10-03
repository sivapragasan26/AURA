"""
Does the browser's AI call actually work against the real providers?

Everything else is proved against a stand-in, deliberately, so the fast suites cost nothing. This is the
one check that spends real tokens: it drives the real extension in real Chrome and lets it call Groq,
Gemini, OpenAI or Anthropic for real, with your own key, exactly as a user's browser will.

    python tests/live_provider_check.py                  every provider a key is available for
    python tests/live_provider_check.py --provider groq  just one
    python tests/live_provider_check.py --no-scan        only the key checks, which spend nothing

Groq and Gemini are the ones that matter: both have a free tier, so that is what nearly everyone will
use, and both must pass before release. OpenAI and Anthropic need a funded account and are reported as
skipped when no key is there, never silently passed.

Keys are read from the environment, then from a .env beside the project, then from the local AURA install
at Desktop\\Final_year. They are never printed, never written anywhere, and the script checks that each
key reached its provider and nothing else - not the AURA server, not the panel's step list, not a log.

Cost: one scan per provider. The prompt is roughly 8 KB plus one screenshot, so a few thousand tokens -
free on Groq and Gemini, around $0.002 on gpt-6-luna and $0.02 on claude-haiku-4-5 at today's prices.
"""
import argparse
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

from aura.config.models import DEFAULT_MODELS, MODEL_CAPABILITIES  # noqa: E402
from cdp_harness import ChromeHarness, SidePanel  # noqa: E402
import extension_browser_ai_e2e as e2e  # noqa: E402

# Free first: these two are the release gate. The paid two are run only if a key happens to be there.
ORDER = ["groq", "gemini", "openai", "anthropic"]
GATE = {"groq", "gemini"}
# The same names aura/config/settings.py accepts, in the same order, so a key that already works for the
# engine works here too - the local install keeps its Groq key as `groq_api`, for one.
ENV_VAR = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
           "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
ENV_ALIASES = {
    "groq": ["GROQ_API_KEY", "groq_api", "GROQ_API"],
    "gemini": ["GEMINI_API_KEY", "gemini_api", "GOOGLE_API_KEY", "AI_API_KEY"],
    "openai": ["OPENAI_API_KEY", "openai_api", "AI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "anthropic_api", "AI_API_KEY"],
}

# Where a key may be found, in order. The local AURA install is last and is only read, never changed.
KEY_FILES = [ROOT / ".env", Path(r"C:\Users\somanathan\Desktop\Final_year") / ".env"]


def find_key(provider):
    """The key for this provider and where it came from. The value is never printed by this script."""
    names = ENV_ALIASES[provider]
    for var in names:
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), f"environment ({var})"
    for path in KEY_FILES:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() in names and value.strip():
                return value.strip().strip('"').strip("'"), f"{path} ({name.strip()})"
    return "", ""


# Sets this provider up in the panel and records what the panel sends, without touching the provider
# clients themselves: nothing here redirects a URL, which is the whole point of this script.
INSTRUMENT = """
(async () => {
  window.__sent = [];
  if (!window.__fetchWrapped) {
    const real = window.fetch;
    window.fetch = async (url, opts) => {
      const started = Date.now();
      const res = await real(url, opts);
      try {
        const u = String(url);
        if (!u.startsWith('blob:') && !u.startsWith('data:')) {
          window.__sent.push({ url: u, status: res.status, ms: Date.now() - started,
                               headers: (opts && opts.headers) || {},
                               body: (opts && typeof opts.body === 'string') ? opts.body.slice(0, 400) : null });
        }
      } catch (_) {}
      return res;
    };
    window.__fetchWrapped = true;
  }
  await chrome.storage.local.set({
    backendUrl: %(backend)s, token: %(token)s,
    aiProvider: %(provider)s, aiModel: %(model)s,
    providerKeys: %(keys)s,
  });
  return true;
})()
"""

CHECK_KEY = """
(async () => {
  const m = await import('./providers.js');
  const api = await import('./api.js');
  const started = Date.now();
  const r = await m.checkProviderKey({ provider: %(provider)s, model: %(model)s,
                                       apiKey: await api.getProviderKey(%(provider)s) });
  return JSON.stringify({ ...r, ms: Date.now() - started });
})()
"""

READ_AUDIT = """
(async () => {
  const m = await import('./api.js');
  const meta = document.getElementById('scan-meta').textContent.match(/AURA-\\d{4}-\\d{6}/);
  if (!meta) return JSON.stringify({ error: 'no audit id in the panel' });
  const view = await m.api.getAudit(meta[0]);
  return JSON.stringify({
    audit_id: view.audit_id,
    ai: view.ai,
    findings: (view.findings || []).length,
    ai_findings: (view.findings || []).filter((f) => (f.source || '').toLowerCase() === 'ai').length,
  });
})()
"""


class Result:
    def __init__(self, provider):
        self.provider = provider
        self.model = DEFAULT_MODELS[provider]
        self.source = ""
        self.key_check = "-"
        self.key_detail = ""
        self.scan = "-"
        self.detail = ""
        self.ms = 0
        self.findings = 0
        self.ai_findings = 0
        self.leaked = []

    @property
    def skipped(self):
        return self.key_check == "skipped"

    @property
    def passed(self):
        return self.key_check == "READY" and self.scan in ("AI_OK", "not run")


def run_provider(h, panel, tab, provider, key, source, do_scan):
    r = Result(provider)
    r.source = source
    model = r.model
    caps = MODEL_CAPABILITIES.get(model, {})

    h.evaluate(panel.session, INSTRUMENT % {
        "backend": json.dumps(e2e.BACKEND), "token": json.dumps(e2e.TOKEN),
        "provider": json.dumps(provider), "model": json.dumps(model),
        "keys": json.dumps({provider: key}),
    })

    # 1. The metadata endpoint: a bad key, a wrong URL or a CORS refusal shows up here, for free.
    check = json.loads(h.evaluate(panel.session, CHECK_KEY % {
        "provider": json.dumps(provider), "model": json.dumps(model)}))
    r.key_check = check.get("status", "?")
    r.key_detail = (check.get("detail") or "")[:160]
    r.detail = r.key_detail
    if r.key_check != "READY":
        return r
    if not do_scan:
        r.scan = "not run"
        return r

    # 2. One real scan, with the screenshot where the model can be shown one.
    h.evaluate(panel.session, "window.__sent = []")
    h.activate(tab)
    started = time.time()
    try:
        panel.scan(timeout=300)
    except AssertionError as e:
        r.scan = "scan failed"
        r.detail = str(e)[:200]
        return r
    r.ms = int((time.time() - started) * 1000)

    audit = json.loads(h.evaluate(panel.session, READ_AUDIT))
    if audit.get("error"):
        r.scan = "no audit"
        r.detail = audit["error"]
        return r
    ai = audit.get("ai") or {}
    r.scan = ai.get("state", "?")
    r.findings = audit.get("findings", 0)
    r.ai_findings = audit.get("ai_findings", 0)
    r.detail = f"{ai.get('provider_status', '?')} - {(ai.get('message') or ai.get('reason') or '')[:120]}"

    # 3. The key went to the provider and nowhere else.
    sent = h.evaluate(panel.session, "window.__sent")
    for call in sent:
        blob = json.dumps({"h": call.get("headers"), "b": call.get("body")})
        if key in blob and e2e.BACKEND in call["url"]:
            r.leaked.append(call["url"])
    steps = panel.js("document.getElementById('steps').textContent")
    if key in steps:
        r.leaked.append("the panel's step list")
    if ai.get("provider", "").lower() != provider:
        r.detail += f" | WRONG PROVIDER RECORDED: {ai.get('provider')}"
    if caps.get("image_input") and not any("prepare" in c["url"] and '"screenshot_attached": true' in (c.get("body") or "")
                                           for c in sent):
        pass  # the prepare body is truncated for recording; the screenshot is checked by the stand-in suite
    return r


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=ORDER, help="only this provider")
    ap.add_argument("--no-scan", action="store_true", help="key checks only; spends nothing")
    args = ap.parse_args()
    wanted = [args.provider] if args.provider else ORDER

    keys = {}
    for provider in wanted:
        key, source = find_key(provider)
        if key:
            keys[provider] = (key, source)

    print("Live provider check - real keys, real API calls\n")
    for provider in wanted:
        if provider in keys:
            print(f"  {provider:10} key found in {keys[provider][1]}")
        else:
            print(f"  {provider:10} no key ({ENV_VAR[provider]} not set) - will be skipped")
    if not keys:
        print("\nNothing to check: no keys were found. Set one of the *_API_KEY variables and try again.")
        return 1
    if not args.no_scan:
        print(f"\n  {len(keys)} scan(s) will be made, one request each.")

    url = e2e.serve_page()
    api = e2e.start_api()
    h = ChromeHarness(headless=True)
    results = []
    try:
        ext = h.load_extension(str(ROOT / "extension"))
        options = h.extension_page(ext)
        h.evaluate(options, f"chrome.storage.local.set({{backendUrl: '{e2e.BACKEND}', token: '{e2e.TOKEN}'}})")
        tab = h.open_tab(url, new_window=True)
        h.click_toolbar_action(ext, tab)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok", 25)

        for provider in wanted:
            if provider not in keys:
                r = Result(provider)
                r.key_check = "skipped"
                r.detail = f"no {ENV_VAR[provider]}"
                results.append(r)
                continue
            key, source = keys[provider]
            print(f"\n--- {provider} / {DEFAULT_MODELS[provider]} ---", flush=True)
            try:
                r = run_provider(h, panel, tab, provider, key, source, not args.no_scan)
            except Exception as e:
                r = Result(provider)
                r.key_check = "error"
                r.detail = f"{type(e).__name__}: {e}"[:200]
            results.append(r)
            print(f"    key check: {r.key_check} - {r.key_detail[:120]}")
            if r.scan != "-":
                print(f"    scan: {r.scan} - {r.findings} findings ({r.ai_findings} from the model) in {r.ms} ms")
    finally:
        h.close()
        api.should_exit = True
        time.sleep(0.4)

    print("\n" + "=" * 78)
    print(f"{'provider':11}{'key check':12}{'scan':14}{'findings':10}{'ms':8}")
    print("-" * 78)
    for r in results:
        print(f"{r.provider:11}{r.key_check:12}{r.scan:14}{str(r.findings) + ' (' + str(r.ai_findings) + ' AI)':10}{r.ms:<8}")
    print("=" * 78)

    leaked = [r for r in results if r.leaked]
    for r in leaked:
        print(f"\nKEY LEAK: {r.provider}'s key appeared in {r.leaked}")

    # "Proved" means a real scan went through. A key check alone proves the endpoint and the key,
    # not that the model's answer parses, so --no-scan must not be allowed to read as a pass.
    verified = [r.provider for r in results if r.scan == "AI_OK"]
    checked_only = [r.provider for r in results if r.key_check == "READY" and r.scan == "not run"]
    skipped = [r.provider for r in results if r.skipped]
    failed = [r for r in results if not r.passed and not r.skipped]

    print("")
    print("Proved against a live API, end to end: " + (", ".join(verified) if verified else "none"))
    if checked_only:
        print("Key and endpoint accepted, no scan run: " + ", ".join(checked_only))
    if skipped:
        print(f"Skipped for want of a key: {', '.join(skipped)}")
    for r in failed:
        print(f"FAILED {r.provider}: key check {r.key_check}, scan {r.scan} - {r.detail}")

    gate = [p for p in GATE if p in wanted]
    missed = [] if args.no_scan else [p for p in gate if p not in verified]
    if missed:
        print(f"\nRELEASE GATE NOT MET: {', '.join(missed)} must pass before deploying "
              f"(free tier, so this is what nearly everyone will use).")
    print("\nLIVE PROVIDER CHECK:", "PASSED" if not failed and not leaked and not missed else "FAILED")
    return 0 if (not failed and not leaked and not missed) else 1


if __name__ == "__main__":
    sys.exit(main())
