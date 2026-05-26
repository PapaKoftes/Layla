"""Backward compatibility -- module moved to services/planning/verification_queue.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.verification_queue")
_sys.modules[__name__] = _real
