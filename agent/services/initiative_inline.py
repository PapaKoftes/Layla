"""Backward compatibility -- module moved to services/infrastructure/initiative_inline.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.initiative_inline")
_sys.modules[__name__] = _real
