"""Backward compatibility -- module moved to services/safety/agent_safety.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.agent_safety")
_sys.modules[__name__] = _real
