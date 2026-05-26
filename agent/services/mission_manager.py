"""Backward compatibility -- module moved to services/planning/mission_manager.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.mission_manager")
_sys.modules[__name__] = _real
