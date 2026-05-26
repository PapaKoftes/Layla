"""Backward compatibility -- module moved to services/planning/engine_plans.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.engine_plans")
_sys.modules[__name__] = _real
