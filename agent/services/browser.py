"""Backward compatibility -- module moved to services/infrastructure/browser.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.browser")
_sys.modules[__name__] = _real
