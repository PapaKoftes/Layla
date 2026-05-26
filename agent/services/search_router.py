"""Backward compatibility -- module moved to services/retrieval/search_router.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.retrieval.search_router")
_sys.modules[__name__] = _real
