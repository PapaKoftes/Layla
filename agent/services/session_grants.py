"""Backward compatibility -- module moved to services/safety/session_grants.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.session_grants")
_sys.modules[__name__] = _real
