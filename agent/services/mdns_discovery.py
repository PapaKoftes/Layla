"""Backward compatibility -- module moved to services/cluster/mdns_discovery.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.cluster.mdns_discovery")
_sys.modules[__name__] = _real
