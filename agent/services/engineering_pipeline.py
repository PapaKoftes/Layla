"""Backward compatibility -- module moved to services/planning/engineering_pipeline.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.engineering_pipeline")
_sys.modules[__name__] = _real
