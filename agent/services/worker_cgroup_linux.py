"""Backward compatibility -- module moved to services/infrastructure/worker_cgroup_linux.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.worker_cgroup_linux")
_sys.modules[__name__] = _real
