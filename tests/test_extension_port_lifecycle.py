"""
Regression guard: the side panel must never use a disconnected runtime Port.

Bug (fixed): panel.js created one Port at load and kept it forever. Chrome stops an idle MV3 service worker
(~30 s), which disconnects the Port; a panel action then called port.postMessage() on it and showed
"Attempting to use a disconnected port object". Real-browser proof: tests/extension_tabsync_e2e.py.
"""
import re
from pathlib import Path

PANEL = (Path(__file__).resolve().parents[1] / "extension" / "sidepanel" / "panel.js").read_text(encoding="utf-8")
BACKGROUND = (Path(__file__).resolve().parents[1] / "extension" / "background.js").read_text(encoding="utf-8")


def test_panel_port_is_not_a_permanent_constant_and_handles_disconnect():
    assert not re.search(r"const\s+port\s*=\s*chrome\.runtime\.connect", PANEL)
    connect = PANEL[PANEL.index("function connectPort"):PANEL.index("function ensurePort")]
    assert "onDisconnect.addListener" in connect
    assert re.search(r"if \(port === p\) port = null", connect), "a disconnected port reference must be dropped"


def test_every_post_goes_through_the_reconnecting_helper():
    posts = [m.start() for m in re.finditer(r"port\.postMessage\(", PANEL)]
    helper = (PANEL.index("function markTouched"), PANEL.index("function untouch"))
    assert posts and all(helper[0] < p < helper[1] for p in posts), "raw port.postMessage outside markTouched"
    assert "p.postMessage" in PANEL  # re-announce on the fresh port inside connectPort


def test_users_never_see_raw_page_communication_errors():
    for handler in ("async function doHighlight",):
        body = PANEL[PANEL.index(handler):]
        body = body[:body.index("\n}\n")]
        catch = body[body.rindex("} catch (e) {"):]
        assert "e.message" not in catch, f"{handler} shows the raw error"
        assert "pageUnavailable(" in catch
    assert "Highlight isn't available on this page right now." in PANEL


def test_background_tracks_touched_tabs_per_port():
    handler = BACKGROUND[BACKGROUND.index("chrome.runtime.onConnect.addListener"):]
    assert "const touchedTabs = new Set()" in handler
