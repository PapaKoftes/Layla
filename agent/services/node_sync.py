"""Backward compatibility -- module moved to services/cluster/node_sync.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.cluster.node_sync")
_sys.modules[__name__] = _real
