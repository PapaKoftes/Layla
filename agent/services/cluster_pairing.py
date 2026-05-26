"""Backward compatibility -- module moved to services/cluster/cluster_pairing.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.cluster.cluster_pairing")
_sys.modules[__name__] = _real
