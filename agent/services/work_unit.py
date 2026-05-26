"""Backward compatibility -- module moved to services/cluster/work_unit.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.cluster.work_unit")
_sys.modules[__name__] = _real
