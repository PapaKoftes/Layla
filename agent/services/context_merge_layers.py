"""Backward compatibility -- module moved to services/context/context_merge_layers.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.context.context_merge_layers")
_sys.modules[__name__] = _real
