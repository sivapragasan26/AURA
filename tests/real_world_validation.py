"""
Real-world validation of the AURA side panel on live public websites.

    python tests/real_world_validation.py                  # every site below
    python tests/real_world_validation.py amazon_search    # one site

For each site this drives the REAL extension in real Chrome exactly as a person would: click the AURA
toolbar icon on the tab, click Scan current page, open every finding, read what the panel shows, try
Highlight, and ask Ask AURA a question on two different findings to prove the answers stay scoped.

It records, per finding: the human title / summary / why / fix / where, the status and the conclusion (so a
contradiction is visible), the finding-level evidence checklist, and what Highlight actually did. Output
goes to runs/real_world/<site>.json plus a screenshot of the panel.

This uses the provider configured on the AURA server. With a real provider each scan costs 1 AI request and
each non-standard Ask AURA question costs 1 more; the standard questions cost none. Nothing is submitted on
the pages: the scan is read-only and safe interactions stay off.
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

from cdp_harness import ChromeHarness, SidePanel  # noqa: E402
from extension_e2e import BACKEND_URL, TOKEN, start_api  # noqa: E402

EXT = str(ROOT / "extension")
OUT = ROOT / "runs" / "real_world"

SITES = {
    "amazon_search": "https://www.amazon.in/s?k=wireless+headphones",
    "amazon_product": "https://www.amazon.in/dp/B09G9BL5CP",
    "bookmyshow": "https://in.bookmyshow.com/explore/movies-pondicherry",
    "github_repo": "https://github.com/anthropics/anthropic-sdk-python",
    "github_issues": "https://github.com/anthropics/anthropic-sdk-python/issues",
    "spotify": "https://open.spotify.com/",
    "youtube": "https://www.youtube.com/",
}

# Reading the whole panel for one finding, in the order a person reads it.
READ_FINDING = """(row) => {
  row.click();
  const t = (id) => { const e = document.getElementById(id); return e ? e.textContent.trim() : null; };
  const badges = [...document.querySelectorAll('#d-badges .badge')].map((b) => b.textContent.trim());
  const checklist = [...document.querySelectorAll('#d-ev-checklist li')].map((li) => li.textContent.trim());
  const conclusion = t('d-ev-conclusion');
  document.getElementById('tech-details').open = true;
  const facts = {};
  const dl = document.getElementById('d-facts');
  for (let i = 0; i < dl.children.length; i += 2) {
    facts[dl.children[i].textContent.trim()] = dl.children[i + 1].textContent.trim();
  }
  document.getElementById('tech-details').open = false;
  return {
    id: row.dataset.id, rule: row.dataset.rule, badges,
    title: t('d-title'), status: t('d-status'), what: t('d-desc'), why: t('d-why'),
    fix: t('d-fix'), where: t('d-target'), meaning: t('d-meaning'),
    observed: t('d-ev-observation'), reproduction: t('d-ev-reproduction'),
    evidence_checklist: checklist, conclusion,
    area_note: t('d-area-note'),
    highlight_offered: !document.getElementById('act-highlight').classList.contains('hidden'),
    technical: facts,
  };
}"""


def log(msg):
    print(msg, flush=True)


def select_provider(panel, provider):
    """Picks the AI provider through the real panel UI, exactly as a person would."""
    if not panel.visible("provider-card"):
        panel.js("document.getElementById('provider-toggle').click()")
    panel.wait("!document.getElementById('provider-card').classList.contains('hidden')")
    panel.wait("document.getElementById('provider-select').options.length > 1")
    panel.js("(() => { const s = document.getElementById('provider-select');"
             f" s.value = '{provider}'; s.dispatchEvent(new Event('change')); }})()")
    panel.js("document.getElementById('provider-save').click()")
    panel.wait("document.getElementById('provider-status').textContent.includes('Saved')", 30)
    panel.js("document.getElementById('provider-test').click()")
    panel.wait("!document.getElementById('provider-status').textContent.includes('Testing')", 45)
    status = panel.text("provider-status")
    panel.js("document.getElementById('provider-close').click()")
    return status


def read_findings(panel):
    panel.js(f"window.__auraRead = {READ_FINDING}")
    count = panel.js("document.querySelectorAll('#findings .finding').length")
    out = []
    for i in range(count):
        out.append(panel.js(
            f"(() => {{ const rows = [...document.querySelectorAll('#findings .finding')];"
            f" const r = window.__auraRead(rows[{i}]); document.getElementById('back').click(); return r; }})()"))
    return out


def try_highlight(panel, index):
    panel.js(f"[...document.querySelectorAll('#findings .finding')][{index}].click()")
    if panel.js("document.getElementById('act-highlight').classList.contains('hidden')"):
        note = panel.js("document.getElementById('d-area-note').textContent")
        panel.js("document.getElementById('back').click()")
        return {"offered": False, "note": note}
    panel.js("document.getElementById('act-highlight').click()")
    try:
        panel.wait("!document.getElementById('act-out').classList.contains('hidden')", 20)
        result = panel.text("act-out").replace("\n", " | ")
    except AssertionError:
        result = "(no response within 20s)"
    panel.js("document.getElementById('back').click()")
    return {"offered": True, "result": result}


def ask(panel, index, question, timeout=90):
    """Opens finding #index, asks one question, and returns what the panel showed."""
    panel.js(f"[...document.querySelectorAll('#findings .finding')][{index}].click()")
    fid = panel.js("document.querySelector('#d-badges') && "
                   "[...document.querySelectorAll('#findings .finding')].length ? "
                   f"[...document.querySelectorAll('#findings .finding')][{index}].dataset.id : null")
    title = panel.text("d-title")
    before = panel.js("document.getElementById('ask-log').children.length")
    panel.js(f"(() => {{ const i = document.getElementById('ask-input'); i.value = {json.dumps(question)};"
             " document.getElementById('ask-form').dispatchEvent(new Event('submit', {cancelable: true})); })()")
    try:
        panel.wait(f"document.getElementById('ask-log').children.length > {before + 1} && "
                   "!document.getElementById('ask-log').lastElementChild.textContent.includes('Thinking')", timeout)
    except AssertionError:
        pass
    answer = panel.js("document.getElementById('ask-log').lastElementChild.textContent")
    panel.js("document.getElementById('back').click()")
    return {"finding_id": fid, "finding_title": title, "question": question, "answer": answer}


def validate(h, ext, name, url, results):
    log(f"\n=== {name}: {url}")
    tab = h.open_tab(url, new_window=True, wait=False)
    try:
        h.wait_loaded(tab, timeout=60)
    except Exception:
        log("  (load did not settle; continuing)")
    time.sleep(4)  # let client-rendered sites paint
    h.click_toolbar_action(ext, tab)
    panel = SidePanel(h, ext)
    panel.wait_access("access-ok", 30)
    record = {"site": name, "url": url}
    try:
        panel.scan(timeout=240)
    except AssertionError as e:
        record["scan_error"] = str(e)
        log(f"  SCAN FAILED: {e}")
        results[name] = record
        h.close_tab(tab)
        return

    record["audit_id"] = panel.js("(document.getElementById('scan-meta').textContent.match(/AURA-\\d{4}-\\d{6}/) || [])[0]")
    record["page_url_shown"] = panel.js("document.getElementById('state-banner').innerText").split("\n")[1:2]
    record["banner"] = panel.js("document.getElementById('state-banner').innerText").replace("\n", " | ")
    record["scores"] = panel.js("document.getElementById('scores').innerText").replace("\n", " ")
    record["rejected"] = panel.js("document.getElementById('rejected').textContent").replace("\n", " | ")
    record["scan_meta"] = panel.js("document.getElementById('scan-meta').textContent").replace("\n", " | ")
    record["findings"] = read_findings(panel)
    log(f"  audit {record['audit_id']} · {len(record['findings'])} findings")

    record["highlight"] = []
    for i in range(min(3, len(record["findings"]))):
        r = try_highlight(panel, i)
        record["highlight"].append({"finding": record["findings"][i]["id"], **r})
        log(f"  highlight {record['findings'][i]['id']}: {r}")

    # Ask AURA on two different findings, with the same question, to prove the answers stay scoped.
    record["ask"] = []
    if len(record["findings"]) >= 2:
        for i in (0, 1):
            a = ask(panel, i, "how to solve")
            record["ask"].append(a)
            log(f"  ask[{a['finding_id']}] -> {a['answer'][:120]}")
    if len(record["findings"]) >= 1:
        record["ask"].append(ask(panel, 0, "did you see this in the screenshot?"))

    # The exact BookMyShow regression: a free-form question (so the model, not the recorded answer, replies)
    # asked on the region finding, then on the heading finding. Neither may come back about anything else.
    by_rule = {(f.get("rule") or ""): i for i, f in enumerate(record["findings"])}
    for rule, question in (("region", "but its already divided into sections"),
                           ("heading-order", "how to solve"),
                           ("heading_order", "how to solve")):
        if rule in by_rule:
            record["ask"].append({"probe": rule, **ask(panel, by_rule[rule], question, timeout=120)})
            log(f"  ask[{rule}] -> {record['ask'][-1]['answer'][:140]}")

    OUT.mkdir(parents=True, exist_ok=True)
    panel.screenshot(str(OUT / f"{name}.png"))
    results[name] = record
    h.close_tab(tab)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    provider = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--provider=")), "groq")
    wanted = args or list(SITES)
    watchdog = threading.Timer(3000, lambda: (print("FAIL global timeout", flush=True), os._exit(3)))
    watchdog.daemon = True
    watchdog.start()

    api = start_api()
    h = ChromeHarness(headless=True)
    results = {}
    try:
        ext = h.load_extension(EXT)
        sp = h.extension_page(ext)
        h.evaluate(sp, f"chrome.storage.local.set({{backendUrl: '{BACKEND_URL}', token: '{TOKEN}'}})")

        # Choose the provider through the panel's own AI card before any scan.
        boot = h.open_tab("https://example.com/", new_window=True)
        h.click_toolbar_action(ext, boot)
        boot_panel = SidePanel(h, ext)
        results["_provider"] = {"requested": provider, "test_connection": select_provider(boot_panel, provider)}
        log(f"provider {provider}: {results['_provider']['test_connection']}")
        h.close_tab(boot)

        for name in wanted:
            if name not in SITES:
                log(f"unknown site: {name}")
                continue
            try:
                validate(h, ext, name, SITES[name], results)
            except Exception as e:  # one site failing must not lose the others
                results[name] = {"site": name, "url": SITES[name], "error": f"{type(e).__name__}: {e}"}
                log(f"  ERROR {type(e).__name__}: {e}")
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        log(f"\nwrote {OUT / 'summary.json'}")
        h.close()
        api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
