"""Backward compatibility -- module moved to services/infrastructure/outcome_writer.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.outcome_writer")
_sys.modules[__name__] = _real
