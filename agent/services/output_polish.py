"""Backward compatibility -- module moved to services/infrastructure/output_polish.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.output_polish")
_sys.modules[__name__] = _real
