"""Backward compatibility -- module moved to services/infrastructure/tts.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.tts")
_sys.modules[__name__] = _real
