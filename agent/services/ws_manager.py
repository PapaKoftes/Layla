"""Backward compatibility -- module moved to services/infrastructure/ws_manager.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.ws_manager")
_sys.modules[__name__] = _real
