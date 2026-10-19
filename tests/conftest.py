import pytest


@pytest.fixture(autouse=True)
def no_real_anthropic_key(monkeypatch):
    """No test takes the real key from .env or spends money (step 3, 03.10)."""
    monkeypatch.setattr("jobbot.rank.api_key", lambda: None)


