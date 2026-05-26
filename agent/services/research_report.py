"""Backward compatibility -- module moved to services/infrastructure/research_report.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.research_report")
_sys.modules[__name__] = _real
