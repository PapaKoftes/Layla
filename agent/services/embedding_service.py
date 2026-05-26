"""Backward compatibility -- module moved to services/llm/embedding_service.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.embedding_service")
_sys.modules[__name__] = _real
