"""Backward compatibility -- module moved to services/infrastructure/benchmark_suite.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.benchmark_suite")
_sys.modules[__name__] = _real
