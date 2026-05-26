"""Backward compatibility -- module moved to services/context/context_manager.py

This shim registers the real module under both names so that
``patch("services.context_manager.X")`` in tests still works.
"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.context.context_manager")

# Re-register the real module object under the old dotted name so that
# ``import services.context_manager`` and ``patch("services.context_manager.X")``
# both resolve to the canonical module, keeping monkeypatching transparent.
_sys.modules[__name__] = _real
