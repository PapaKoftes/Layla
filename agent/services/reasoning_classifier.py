"""Backward compatibility -- module moved to services/infrastructure/reasoning_classifier.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.reasoning_classifier")
_sys.modules[__name__] = _real
