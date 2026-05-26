"""Backward compatibility -- module moved to services/tools/toolchain_awareness.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.tools.toolchain_awareness")
_sys.modules[__name__] = _real
