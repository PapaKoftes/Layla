"""Backward compatibility -- module moved to services/infrastructure/task_context.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.task_context")
_sys.modules[__name__] = _real
