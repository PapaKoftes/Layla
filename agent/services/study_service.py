"""Backward compatibility -- module moved to services/memory/study_service.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.study_service")
_sys.modules[__name__] = _real
