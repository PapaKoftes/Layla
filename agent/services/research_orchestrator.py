"""Backward compatibility -- module moved to services/planning/research_orchestrator.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.research_orchestrator")
_sys.modules[__name__] = _real
