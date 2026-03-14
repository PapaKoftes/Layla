"""
Capability registry. Each capability may have multiple implementations.
Layla selects the best-performing implementation based on benchmarks.
"""
from capabilities.registry import (
    CAPABILITIES,
    get_active_implementation,
    list_implementations,
    register_implementation,
)

__all__ = [
    "CAPABILITIES",
    "get_active_implementation",
    "list_implementations",
    "register_implementation",
]
