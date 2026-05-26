"""Backward compatibility -- module moved to services/llm/llm_gateway.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.llm_gateway")
_sys.modules[__name__] = _real
