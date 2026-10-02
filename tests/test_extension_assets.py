"""The extension must run the engine's exact collector code (one source of truth, no drift)."""
import json
import re
from pathlib import Path

from aura.tools.sync_extension_assets import AXE_SOURCE, AXE_TARGET, DOM_TARGET, EXT, expected_dom_copy


def test_extension_dom_script_matches_engine_script():
    assert DOM_TARGET.read_text(encoding="utf-8") == expected_dom_copy(), \
        "extension/content/dom_extraction.js drifted: run python -m aura.tools.sync_extension_assets"


def test_extension_axe_matches_engine_axe():
    assert AXE_TARGET.read_bytes() == AXE_SOURCE.read_bytes()


def test_manifest_is_least_privilege():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3
    assert set(m["permissions"]) == {"sidePanel", "activeTab", "scripting", "storage"}
    # host access only to the local AURA server; pages are reached through activeTab (user gesture)
    assert all(h.startswith(("http://127.0.0.1", "http://localhost")) for h in m["host_permissions"])
    assert "<all_urls>" not in json.dumps(m) and "tabs" not in m["permissions"] and "debugger" not in m["permissions"]
    assert "content_scripts" not in m  # nothing is injected automatically on page load


def test_extension_contains_no_provider_secrets_or_remote_code():
    for path in Path(EXT).rglob("*"):
        if path.suffix not in (".js", ".html", ".json") or path.name == "axe.min.js":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_\-]{10,}|gsk_[A-Za-z0-9]{10,})", text), path
        assert not re.search(r"(GEMINI|GROQ|OPENAI|ANTHROPIC)_API_KEY", text), path
        assert not re.search(r"<script[^>]+src=[\"']https?://", text), path
        assert "eval(" not in text and "new Function(" not in text, path


def test_panel_never_renders_untrusted_text_as_html():
    for name in ("panel.js", "scanner.js"):
        text = (EXT / "sidepanel" / name).read_text(encoding="utf-8")
        assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", text), name
