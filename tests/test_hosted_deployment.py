"""
Running the API somewhere other than the user's own machine.

The API is a loopback service by default and must stay that way: the Host check is what stops a web page
the user visits from driving a server bound to their own machine. A hosted deployment opts out explicitly,
host by host, and opts into holding nothing on disk.

These tests pin both halves: the local default is unchanged, and the hosted switches do what they claim.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

from aura.api import security
from aura.api.store import AuditStore
from aura.config import settings

ROOT = Path(__file__).resolve().parents[1]
HOSTED_HOST = "aura-api.onrender.com"


# ---------------------------------------------------------------------------------------------------
# The Host check: loopback by default, widened only by naming a host
# ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8765", "localhost", "localhost:8765", "[::1]:8765"])
def test_loopback_is_always_allowed(host, monkeypatch):
    monkeypatch.delenv("AURA_ALLOWED_HOSTS", raising=False)
    assert security.host_allowed(host)


@pytest.mark.parametrize("host", [HOSTED_HOST, "evil.example", "10.0.0.5", "aura.fly.dev", ""])
def test_a_public_host_is_refused_unless_it_is_named(host, monkeypatch):
    """The default must stay exactly as strict as before this work."""
    monkeypatch.delenv("AURA_ALLOWED_HOSTS", raising=False)
    assert not security.host_allowed(host)


def test_naming_the_host_allows_only_that_host(monkeypatch):
    monkeypatch.setenv("AURA_ALLOWED_HOSTS", HOSTED_HOST)
    assert security.host_allowed(HOSTED_HOST)
    assert security.host_allowed(f"{HOSTED_HOST}:443")
    assert security.host_allowed("127.0.0.1")           # loopback is never withdrawn
    assert not security.host_allowed("evil.example")    # nothing else is let in
    assert not security.host_allowed("sub." + HOSTED_HOST)


def test_several_hosts_can_be_named(monkeypatch):
    monkeypatch.setenv("AURA_ALLOWED_HOSTS", f" {HOSTED_HOST} , aura-staging.onrender.com ")
    assert security.host_allowed(HOSTED_HOST)
    assert security.host_allowed("aura-staging.onrender.com")
    assert not security.host_allowed("other.onrender.com")


def test_a_missing_host_header_is_refused(monkeypatch):
    monkeypatch.setenv("AURA_ALLOWED_HOSTS", HOSTED_HOST)
    assert not security.host_allowed(None)


# ---------------------------------------------------------------------------------------------------
# Persistence: a hosted deployment writes nothing about anyone's page
# ---------------------------------------------------------------------------------------------------
def test_persistence_is_on_by_default():
    """A local install keeps behaving as it always has — the Test Lab and screenshots depend on it."""
    assert settings.PERSIST is True


def test_ensure_dir_creates_nothing_when_persistence_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", False)
    target = tmp_path / "should-not-appear"
    assert settings.ensure_dir(target) is False
    assert not target.exists()


def test_ensure_dir_survives_a_read_only_filesystem(monkeypatch):
    """The process must start even where it cannot write, rather than dying at import."""
    monkeypatch.setattr(settings, "PERSIST", True)

    def refuse(*a, **kw):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", refuse)
    assert settings.ensure_dir(Path("/nowhere/at/all")) is False


def test_an_audit_is_kept_in_memory_and_not_written(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path)
    store = AuditStore()
    view = {"audit_id": "AURA-2026-700001", "page_url": "https://example.com/private", "findings": []}
    store.put(view)

    assert store.get("AURA-2026-700001") == view          # still served
    assert list(tmp_path.iterdir()) == []                  # but nothing on disk
    assert not (tmp_path / "AURA-2026-700001").exists()


def test_the_token_is_not_written_when_persistence_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.delenv("AURA_API_TOKEN", raising=False)
    target = tmp_path / ".aura_api_token"
    token = security.load_or_create_token(target)
    assert len(token) >= 24
    assert not target.exists(), "a hosted deployment must not write a token file"


def test_the_token_is_still_written_for_a_local_install(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", True)
    monkeypatch.delenv("AURA_API_TOKEN", raising=False)
    target = tmp_path / ".aura_api_token"
    token = security.load_or_create_token(target)
    assert target.read_text(encoding="utf-8").strip() == token


def test_the_environment_token_wins_over_any_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AURA_API_TOKEN", "from-the-platform-secret-store-0123")
    target = tmp_path / ".aura_api_token"
    target.write_text("a-stale-file-token-that-must-be-ignored", encoding="utf-8")
    assert security.load_or_create_token(target) == "from-the-platform-secret-store-0123"


# ---------------------------------------------------------------------------------------------------
# The image: no browser binaries
# ---------------------------------------------------------------------------------------------------
def test_the_api_imports_without_playwright_installed():
    """
    The extension collects its own evidence, so the hosted API never drives a browser. Importing it must
    not require Playwright, or the image would need ~1 GB of browser binaries for nothing.
    """
    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "playwright" or name.startswith("playwright."):
                raise ImportError(f"{name} is not installed in this image")
            return None

    dropped = {name: mod for name, mod in list(sys.modules.items())
               if name.startswith(("aura", "playwright"))}
    for name in dropped:
        del sys.modules[name]
    blocker = Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        importlib.import_module("aura.api.server")
        assert "playwright" not in sys.modules
    finally:
        sys.meta_path.remove(blocker)
        for name in [n for n in list(sys.modules) if n.startswith("aura")]:
            del sys.modules[name]
        sys.modules.update(dropped)


def test_no_module_under_aura_imports_playwright_at_module_level():
    offenders = []
    for path in (ROOT / "aura").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("from playwright", "import playwright")) and not line.startswith(("    ", "\t")):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, f"module-level playwright imports: {offenders}"


# ---------------------------------------------------------------------------------------------------
# What the deployment actually installs and runs
# ---------------------------------------------------------------------------------------------------
def _declared(path: Path) -> str:
    """Only the requirement lines, so prose in comments is not mistaken for a dependency."""
    lines = [l.split("#", 1)[0].strip().lower() for l in path.read_text(encoding="utf-8").splitlines()]
    return chr(10).join(l for l in lines if l)


def test_api_requirements_are_complete_and_slim():
    api = _declared(ROOT / "requirements.txt")
    for needed in ("starlette", "uvicorn", "pydantic", "python-dotenv", "pillow"):
        assert needed in api, f"the API cannot start without {needed}"
    for unwanted in ("playwright", "streamlit", "pytest"):
        assert unwanted not in api, f"{unwanted} does not belong in the hosted image"


def test_dev_requirements_still_cover_the_local_tooling():
    dev = _declared(ROOT / "requirements-dev.txt")
    assert "-r requirements.txt" in dev
    for needed in ("playwright", "streamlit", "pytest", "openai", "anthropic"):
        assert needed in dev


def test_the_dockerfile_installs_no_browser():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "playwright install" not in docker, "the image must not download browser binaries"
    assert "AURA_PERSIST=0" in docker
    assert "AURA_API_HOST=0.0.0.0" in docker
    assert "USER aura" in docker, "the container should not run as root"


def test_the_render_blueprint_keeps_secrets_out_of_the_repo():
    # Declarations only: the file's own comments explain the policy and would otherwise match.
    lines = [l.split("#", 1)[0].rstrip() for l in (ROOT / "render.yaml").read_text(encoding="utf-8").splitlines()]
    blueprint = chr(10).join(l for l in lines if l.strip())
    assert "healthCheckPath: /api/health" in blueprint
    assert "AURA_ALLOWED_HOSTS" in blueprint, "the host check must be configured, never left open"
    # A token or an origin list committed to the repo would be a published secret.
    for secret in ("AURA_API_TOKEN", "AURA_ALLOWED_ORIGINS"):
        index = blueprint.index(secret)
        assert "sync: false" in blueprint[index:index + 120], f"{secret} must be dashboard-only"
    assert "value:" not in blueprint[blueprint.index("AURA_API_TOKEN"):][:80]


def test_the_entry_point_binds_locally_by_default():
    main = (ROOT / "aura" / "api" / "__main__.py").read_text(encoding="utf-8")
    assert 'os.getenv("AURA_API_HOST", "127.0.0.1")' in main, "local default must stay loopback"
    assert 'os.getenv("PORT")' in main, "a hosted platform injects PORT"
    # The pairing token must not reach a hosted platform's log stream.
    assert "if local:" in main
