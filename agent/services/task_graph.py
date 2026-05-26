"""Backward compatibility -- module moved to services/planning/task_graph.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.task_graph")
_sys.modules[__name__] = _real
