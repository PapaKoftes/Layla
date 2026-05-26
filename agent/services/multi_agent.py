"""Backward compatibility -- module moved to services/planning/multi_agent.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.multi_agent")
_sys.modules[__name__] = _real
