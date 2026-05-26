"""Backward compatibility -- module moved to services/context/context_window_ux.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.context.context_window_ux")
_sys.modules[__name__] = _real
