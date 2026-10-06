import pytest

from aura.agent.provider_status import ProviderStateStore
from aura.config import settings

PROVIDER_KEY_SETTINGS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY")


@pytest.fixture(autouse=True)
def isolated_provider_state(tmp_path, monkeypatch):
    """Tests must never write AURA's real tracked provider state (runs/provider_state.json)."""
    monkeypatch.setattr(ProviderStateStore, "path", tmp_path / "provider_state.json")
    yield ProviderStateStore.path


@pytest.fixture(autouse=True)
def no_real_provider_keys(monkeypatch):
    """
    The suite runs as though no provider key were configured, whoever's machine it is on.

    settings.py calls load_dotenv(), so a .env with a real key - which anyone running
    tests/live_provider_check.py now has - silently changes what the suite tests: a route that reports
    NOT_CONFIGURED without a key instead goes and asks the provider, which means the suite makes a
    network call and its result depends on the machine. A test that wants a key sets one itself.
    """
    for name in PROVIDER_KEY_SETTINGS:
        monkeypatch.setattr(settings, name, "", raising=False)
        monkeypatch.delenv(name, raising=False)
    # The aliases settings.py accepts as fallbacks, so a key cannot sneak in through one of those either.
    for alias in ("groq_api", "GROQ_API", "AI_API_KEY", "gemini_api", "openai_api", "anthropic_api"):
        monkeypatch.delenv(alias, raising=False)
    yield


@pytest.fixture(autouse=True)
def fresh_registration_limit():
    """
    Every test starts with the registration limit unspent.

    The limiter counts new installs per client address for an hour, in module state. The test that
    proves it works deliberately exhausts it for 127.0.0.1, and without this every later test that
    registers an install got 429 - a failure in whichever file happens to sort after that one, with
    nothing in it to suggest the cause.
    """
    from aura.api import server as api_server
    api_server._REGISTRATIONS.clear()
    yield
    api_server._REGISTRATIONS.clear()
