"""Backward compatibility -- module moved to services/infrastructure/shell_sessions.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.shell_sessions")
_sys.modules[__name__] = _real
