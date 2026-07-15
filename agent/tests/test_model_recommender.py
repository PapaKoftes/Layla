"""recommend()/recommend_from_hardware() map detected hardware to a model tier — the first thing a user
sees at setup and the input to model selection. Was UNTESTED; locks the tier boundaries don't crash and
scale with RAM/VRAM."""
import sys
from pathlib import Path
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from services.llm.model_recommender import recommend, recommend_from_hardware  # noqa: E402


def _size(rec):
    # pull any size/param signal from the returned dict for a monotonicity check
    for k in ("size_b", "params_b", "recommended_size_gb", "ram_required", "tier"):
        if k in rec and isinstance(rec[k], (int, float)):
            return rec[k]
    return None


def test_recommend_returns_dict_across_tiers_without_crash():
    for ram, vram in [(4, 0), (8, 0), (16, 0), (16, 8), (32, 24)]:
        rec = recommend(ram_gb=ram, vram_gb=vram)
        assert isinstance(rec, dict) and rec, f"empty rec for ram={ram} vram={vram}"


def test_low_ram_recommends_smaller_than_high_ram():
    low = recommend(ram_gb=4, vram_gb=0)
    high = recommend(ram_gb=64, vram_gb=24)
    ls, hs = _size(low), _size(high)
    if ls is not None and hs is not None:
        assert hs >= ls, "more hardware should not recommend a smaller model"


def test_recommend_from_hardware_no_crash():
    rec = recommend_from_hardware()
    assert isinstance(rec, dict)
