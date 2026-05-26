"""Backward compatibility -- module moved to services/infrastructure/background_subprocess.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.background_subprocess")
_sys.modules[__name__] = _real
