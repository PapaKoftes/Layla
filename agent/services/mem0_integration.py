"""Backward compatibility -- module moved to services/retrieval/mem0_integration.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.retrieval.mem0_integration")
_sys.modules[__name__] = _real
