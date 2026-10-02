import pytest

from aura.agent.provider_status import ProviderStateStore


@pytest.fixture(autouse=True)
def isolated_provider_state(tmp_path, monkeypatch):
    """Tests must never write AURA's real tracked provider state (runs/provider_state.json)."""
    monkeypatch.setattr(ProviderStateStore, "path", tmp_path / "provider_state.json")
    yield ProviderStateStore.path
