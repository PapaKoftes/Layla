"""Backward compatibility -- module moved to services/memory/person_dossier.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.person_dossier")
_sys.modules[__name__] = _real
