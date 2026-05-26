"""Backward compatibility -- module moved to services/tools/intent_routing_hints.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.tools.intent_routing_hints")
_sys.modules[__name__] = _real
