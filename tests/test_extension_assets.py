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
    # Host access is allowed to exactly three kinds of place and nowhere else: the AURA service, an AURA
    # server on this machine, and the four AI providers the browser now calls itself. Pages being scanned
    # are reached through activeTab, on a user gesture, and never appear here.
    allowed = {
        "https://aura-api.onrender.com/*",
        "http://127.0.0.1:8765/*",
        "http://localhost:8765/*",
        "https://api.groq.com/*",
        "https://api.openai.com/*",
        "https://generativelanguage.googleapis.com/*",
        "https://api.anthropic.com/*",
    }
    assert set(m["host_permissions"]) <= allowed, sorted(set(m["host_permissions"]) - allowed)
    # The provider origins in the manifest are exactly the ones the extension knows how to call: a
    # permission for a host nothing talks to is a permission that should not be asked for.
    providers_js = (EXT / "sidepanel" / "providers.js").read_text(encoding="utf-8")
    for origin in m["host_permissions"]:
        host = origin.replace("https://", "").replace("http://", "").replace("/*", "")
        if host.startswith(("127.0.0.1", "localhost", "aura-api")):
            continue
        assert host in providers_js, f"{host} is permitted but no provider client uses it"
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


def test_every_module_import_resolves_to_a_real_export():
    """
    A missing export is a blank panel.

    The side panel is ES modules: one name imported that another file does not export stops the whole
    panel from running, with nothing on screen and the reason only in a console a user never opens. This
    is cheap to check and the browser suites take minutes.
    """
    exports = {}
    for path in Path(EXT).rglob("*.js"):
        if path.name == "axe.min.js":
            continue
        text = path.read_text(encoding="utf-8")
        exports[path.name] = set(re.findall(r"export\s+(?:async\s+)?(?:function|const|class)\s+([A-Za-z_$][\w$]*)", text))

    problems = []
    for path in Path(EXT).rglob("*.js"):
        if path.name == "axe.min.js":
            continue
        text = path.read_text(encoding="utf-8")
        for imported, module in re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']", text):
            target = Path(module).name
            if target not in exports:
                problems.append(f"{path.name} imports from {module}, which is not an extension module")
                continue
            for raw in imported.split(","):
                name = raw.strip().split(" as ")[0].strip()
                if name and name not in exports[target]:
                    problems.append(f"{path.name} imports '{name}' from {target}, which does not export it")
    assert not problems, "; ".join(problems)
