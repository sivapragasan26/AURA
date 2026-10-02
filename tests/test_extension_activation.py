"""
Regression guard for the activeTab -> side panel access lifecycle.

Bug (fixed): with sidePanel.setPanelBehavior({openPanelOnActionClick: true}) Chrome opened the panel itself,
never dispatched chrome.action.onClicked and did not grant activeTab, so the panel reported "no access" even
after the user clicked the toolbar icon. The real-browser proof is tests/extension_activation_e2e.py.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_activation_state_machine_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests" / "extension_js" / "activation.test.mjs")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_toolbar_click_is_handled_by_onclicked_not_by_panel_behaviour():
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in bg.splitlines() if not l.strip().startswith("//"))
    assert "openPanelOnActionClick: true" not in code
    assert re.search(r"setPanelBehavior\(\{\s*openPanelOnActionClick:\s*false\s*\}\)", code), \
        "the persisted profile setting must be reset to false on every service-worker start"
    handler = code[code.index("chrome.action.onClicked.addListener"):]
    handler = handler[:handler.index("});")]
    # sidePanel.open must be the first call (it needs the live user gesture), then the tab is activated
    assert handler.index("chrome.sidePanel.open(") < handler.index("activation.activate(tab)")
    assert "await" not in handler.split("chrome.sidePanel.open(")[0]


def test_panel_asks_background_for_current_tab_state_and_gates_scan():
    panel = (EXT / "sidepanel" / "panel.js").read_text(encoding="utf-8")
    html = (EXT / "sidepanel" / "index.html").read_text(encoding="utf-8")
    assert '"GET_TAB_STATE"' in panel and "TAB_ACTIVATED" in panel
    assert 'result.state !== "ACTIVATED"' in panel  # Scan enabled only for an activated, accessible tab
    assert re.search(r'<button id="scan"[^>]*\bdisabled\b', html), "Scan starts disabled until access is confirmed"
    assert "chrome.permissions.contains" not in panel  # cannot see activeTab grants


def test_background_answers_only_extension_pages():
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert "sender.id !== chrome.runtime.id" in bg and "chrome-extension://${chrome.runtime.id}/" in bg


def test_activation_state_is_session_scoped_and_holds_no_page_data():
    act = (EXT / "activation.js").read_text(encoding="utf-8")
    assert "storage.session" in act and "storage.local" not in act
    stored = re.findall(r"map\[tabId\] = (\{[^}]*\})", act)
    assert stored and all(set(re.findall(r"(\w+):", s)) <= {"origin", "activatedAt", "lost"} for s in stored), stored
