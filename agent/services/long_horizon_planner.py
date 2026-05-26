"""Backward compatibility -- module moved to services/planning/long_horizon_planner.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.long_horizon_planner")
_sys.modules[__name__] = _real
