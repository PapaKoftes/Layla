"""Backward compatibility -- module moved to services/safety/decision_policy.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.decision_policy")
_sys.modules[__name__] = _real
