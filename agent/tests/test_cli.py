"""serve.py CLI: --port/--host/--no-browser/--reload map to env vars, --port wins over config."""
from __future__ import annotations

import serve


def test_parse_args_sets_env(monkeypatch):
    monkeypatch.delenv("LAYLA_PORT", raising=False)
    monkeypatch.delenv("LAYLA_NO_BROWSER", raising=False)
    serve._parse_args(["--host", "0.0.0.0", "--port", "9191", "--no-browser", "--reload"])
    import os
    assert os.environ["LAYLA_HOST"] == "0.0.0.0"
    assert os.environ["LAYLA_PORT"] == "9191"
    assert os.environ["LAYLA_NO_BROWSER"] == "1"
    assert os.environ["LAYLA_RELOAD"] == "1"


def test_port_env_overrides_config(monkeypatch):
    monkeypatch.setenv("LAYLA_PORT", "7777")
    assert serve._load_port(default=8000) == 7777
    monkeypatch.setenv("LAYLA_PORT", "not-a-number")  # falls back gracefully
    assert isinstance(serve._load_port(default=8000), int)


def test_help_exits(monkeypatch):
    import pytest
    with pytest.raises(SystemExit):
        serve._parse_args(["--help"])
