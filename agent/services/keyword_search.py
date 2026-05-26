"""Backward compatibility -- module moved to services/retrieval/keyword_search.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.retrieval.keyword_search")
_sys.modules[__name__] = _real
