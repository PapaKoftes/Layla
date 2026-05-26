"""Backward compatibility -- module moved to services/infrastructure/research_profile.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.research_profile")
_sys.modules[__name__] = _real
