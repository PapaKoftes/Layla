"""Backward compatibility -- module moved to services/infrastructure/pre_loop_setup.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.pre_loop_setup")
_sys.modules[__name__] = _real
