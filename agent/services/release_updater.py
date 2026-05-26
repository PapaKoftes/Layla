"""Backward compatibility -- module moved to services/infrastructure/release_updater.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.release_updater")
_sys.modules[__name__] = _real
