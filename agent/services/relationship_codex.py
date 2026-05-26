"""Backward compatibility -- module moved to services/memory/relationship_codex.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.relationship_codex")
_sys.modules[__name__] = _real
