"""Backward compatibility -- module moved to services/safety/admin_checkpoint.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.admin_checkpoint")
_sys.modules[__name__] = _real
