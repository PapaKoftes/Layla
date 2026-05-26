"""Backward compatibility -- module moved to services/memory/graph_reasoning.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.graph_reasoning")
_sys.modules[__name__] = _real
