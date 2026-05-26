"""Backward compatibility -- module moved to services/infrastructure/experience_replay.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.experience_replay")
_sys.modules[__name__] = _real
