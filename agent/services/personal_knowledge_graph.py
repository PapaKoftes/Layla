"""Backward compatibility -- module moved to services/memory/personal_knowledge_graph.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.personal_knowledge_graph")
_sys.modules[__name__] = _real
