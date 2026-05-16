"""Ensure agent/ is on sys.path so imports like `layla.*` and `runtime_safety` resolve
regardless of the working directory pytest is invoked from."""
import sys
from pathlib import Path

_AGENT = Path(__file__).resolve().parent.parent.parent
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))
