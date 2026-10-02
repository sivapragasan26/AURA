"""
Regression guard: side-panel results are owned by (tab, document) and validated before they are shown.

Bug (fixed): the panel kept a single audit plus a sticky `state.stale` message. Switching to another tab set
"These results belong to another tab…", and nothing cleared it on return, so the audited page's findings were
shown next to that message (Flipkart report). Real-browser proof: tests/extension_tabsync_e2e.py.
"""
import re
from pathlib import Path

PANEL = (Path(__file__).resolve().parents[1] / "extension" / "sidepanel" / "panel.js").read_text(encoding="utf-8")


def test_no_sticky_other_tab_flag():
    assert "markStale" not in PANEL
    assert "These results belong to another tab" not in PANEL  # replaced by the per-tab no-audit card


def test_ownership_check_for_page_actions_is_kept():
    body = PANEL[PANEL.index("async function inScannedTab"):]
    body = body[:body.index("\n}\n")]
    assert "tab.id !== state.tabId" in body and "OTHER_TAB" in body


def test_audits_are_keyed_by_tab_and_validated_by_document_identity():
    assert "const audits = new Map()" in PANEL
    assert "res.documentId" in PANEL, "a reload/navigation must be detected by Chrome's documentId"
    sync = PANEL[PANEL.index("async function syncAuditForTab"):PANEL.index("function showNoAudit")]
    for outcome in ('"navigated"', '"reloaded"', "forgetAudit(tab.id)"):
        assert outcome in sync


def test_only_references_are_persisted_in_session_storage():
    save = PANEL[PANEL.index("async function saveAuditRef"):PANEL.index("async function restoreAuditRefs")]
    assert "chrome.storage.session" in save and "storage.local" not in save
    stored = re.search(r"data\[tabId\] = (\{[^}]*\})", save).group(1)
    assert set(re.findall(r"(\w+):", stored)) == {"auditId", "documentId", "pageKey"}  # no findings, no page data


def test_closed_tabs_forget_their_audit():
    removed = PANEL[PANEL.index("chrome.tabs.onRemoved.addListener"):]
    assert "forgetAudit(tabId)" in removed[:200]
