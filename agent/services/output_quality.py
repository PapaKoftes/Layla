"""Backward compatibility -- module moved to services/infrastructure/output_quality.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.output_quality")
_sys.modules[__name__] = _real
