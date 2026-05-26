"""Backward compatibility -- module moved to services/tools/intent_detection.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.tools.intent_detection")
_sys.modules[__name__] = _real
