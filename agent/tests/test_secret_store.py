"""Tests for the OS-keyring secret store (services/secret_store.py, REQ-12).

Uses a fake `keyring` backend injected into sys.modules, so it runs anywhere
(no real OS keyring needed). Verifies the keyring→env→plaintext priority, that
secrets are pulled out of a save body into the keyring, and that EVERYTHING is a
clean no-op when no keyring backend is available (the plaintext path is unchanged).
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def fake_keyring(monkeypatch):
    store = {}
    mod = types.ModuleType("keyring")
    mod.get_password = lambda svc, k: store.get((svc, k))
    mod.set_password = lambda svc, k, v: store.__setitem__((svc, k), v)
    mod.delete_password = lambda svc, k: store.pop((svc, k), None)
    monkeypatch.setitem(sys.modules, "keyring", mod)
    import services.secret_store as s
    importlib.reload(s)
    monkeypatch.delenv("LAYLA_REMOTE_API_KEY", raising=False)
    yield s
    importlib.reload(s)  # restore for other tests


@pytest.fixture
def no_keyring(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import keyring -> ImportError
    import services.secret_store as s
    importlib.reload(s)
    yield s
    monkeypatch.delitem(sys.modules, "keyring", raising=False)
    importlib.reload(s)


def test_priority_keyring_over_env_over_cfg(fake_keyring, monkeypatch):
    s = fake_keyring
    assert s.has_keyring() is True
    s.set_secret("remote_api_key", "from-keyring")
    monkeypatch.setenv("LAYLA_REMOTE_API_KEY", "from-env")
    assert s.get_secret("remote_api_key", "from-cfg") == "from-keyring"   # keyring wins


def test_env_then_cfg_fallback(fake_keyring, monkeypatch):
    s = fake_keyring
    monkeypatch.setenv("LAYLA_DISCORD_BOT_TOKEN", "env-tok")
    assert s.get_secret("discord_bot_token", "cfg-tok") == "env-tok"      # env over cfg
    assert s.get_secret("slack_bot_token", "cfg-only") == "cfg-only"      # cfg fallback


def test_persist_pulls_secrets_into_keyring(fake_keyring):
    s = fake_keyring
    body = {"remote_api_key": "new-secret", "temperature": 0.4, "n_ctx": 4096}
    cleaned, stored = s.persist_secret_keys(dict(body))
    assert "remote_api_key" not in cleaned          # not persisted to config
    assert cleaned["temperature"] == 0.4 and cleaned["n_ctx"] == 4096
    assert stored == ["remote_api_key"]
    assert s.get_secret("remote_api_key") == "new-secret"


def test_resolve_config_overlays_keyring(fake_keyring):
    s = fake_keyring
    s.set_secret("remote_api_key", "kr-secret")
    res = s.resolve_config_secrets({"remote_api_key": "plaintext", "temperature": 0.4})
    assert res["remote_api_key"] == "kr-secret"     # keyring overlays plaintext
    assert res["temperature"] == 0.4                # non-secret untouched


def test_no_keyring_is_a_clean_noop(no_keyring):
    s = no_keyring
    assert s.has_keyring() is False
    assert s.get_secret("remote_api_key", "cfg") == "cfg"                 # falls back to cfg
    assert s.set_secret("remote_api_key", "x") is False
    assert s.resolve_config_secrets({"remote_api_key": "x"}) == {"remote_api_key": "x"}
    assert s.persist_secret_keys({"remote_api_key": "x"}) == ({"remote_api_key": "x"}, [])
