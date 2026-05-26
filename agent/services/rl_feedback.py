"""Backward compatibility -- module moved to services/infrastructure/rl_feedback.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.rl_feedback")
_sys.modules[__name__] = _real
