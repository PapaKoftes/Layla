"""Backward compatibility -- module moved to services/safety/dignity_engine.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.dignity_engine")
_sys.modules[__name__] = _real
