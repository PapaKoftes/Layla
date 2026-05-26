"""Backward compatibility -- module moved to services/planning/task_dispatcher.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.task_dispatcher")
_sys.modules[__name__] = _real
