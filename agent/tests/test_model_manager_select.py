"""select_best_model scores installed GGUFs against the hardware recommendation and picks one. Silently
picking the wrong local model = worse answers / OOM (user-visible). Was UNTESTED; locks the scoring."""
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from services.llm import model_manager as mm  # noqa: E402


def test_prefers_family_match_and_higher_quant():
    fake_models = [
        {"filename": "some-llama-3b-Q4_K_M.gguf"},
        {"filename": "qwen2.5-coder-7b-Q5_K_M.gguf"},   # family match (+2) + Q5 (+1) = 3
        {"filename": "qwen2.5-coder-7b-Q2_K.gguf"},      # family match (+2) = 2
    ]
    with patch("services.llm.model_manager.list_models", return_value=fake_models), \
         patch("services.llm.model_recommender.recommend_from_hardware", return_value={"suggestion": "qwen2.5-coder-7b"}):
        r = mm.select_best_model()
    assert r["ok"] is True
    assert r["filename"] == "qwen2.5-coder-7b-Q5_K_M.gguf", r


def test_empty_model_dir_returns_not_ok_with_suggestion():
    with patch("services.llm.model_manager.list_models", return_value=[]), \
         patch("services.llm.model_recommender.recommend_from_hardware", return_value={"suggestion": "get qwen"}):
        r = mm.select_best_model()
    assert r["ok"] is False and r["filename"] is None and "qwen" in (r.get("suggestion") or "")
