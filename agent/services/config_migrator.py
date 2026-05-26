"""Backward compatibility -- module moved to services/infrastructure/config_migrator.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.config_migrator")
_sys.modules[__name__] = _real
