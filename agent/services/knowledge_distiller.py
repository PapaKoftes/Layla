"""Backward compatibility -- module moved to services/memory/knowledge_distiller.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.knowledge_distiller")
_sys.modules[__name__] = _real
