"""Backward compatibility -- module moved to services/planning/planner.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.planner")
_sys.modules[__name__] = _real
