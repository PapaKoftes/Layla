"""Item 5: opening System Diagnostics stalled the app — it fired heavy blocking backend probes
(/health full payload, /doctor/capabilities) on open, contending with inference on the single-process
server. The heavy sections must be LAZY (loaded on demand), not fetched on open."""
from pathlib import Path

SD = Path(__file__).resolve().parent.parent / "ui" / "components" / "system-diagnostics.js"

def test_heavy_sections_are_lazy():
    src = SD.read_text(encoding="utf-8")
    # the two heaviest probes must be marked lazy
    assert "'/health'" in src and "lazy: true" in src, "resources(/health) must be lazy"
    assert "/doctor/capabilities" in src
    # _load must skip lazy sections (render a Load button) rather than fetch them
    assert "if (s.lazy)" in src and "Load (slow)" in src
