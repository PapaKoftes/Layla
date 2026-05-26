"""Backward compatibility -- module moved to services/planning/cognitive_workspace.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.cognitive_workspace")
_sys.modules[__name__] = _real
