"""Backward compatibility -- module moved to services/retrieval/web_crawler.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.retrieval.web_crawler")
_sys.modules[__name__] = _real
