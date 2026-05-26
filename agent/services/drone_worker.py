"""Backward compatibility -- module moved to services/cluster/drone_worker.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.cluster.drone_worker")
_sys.modules[__name__] = _real
