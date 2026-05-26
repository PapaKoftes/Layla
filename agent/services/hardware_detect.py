"""Backward compatibility -- module moved to services/infrastructure/hardware_detect.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.hardware_detect")
_sys.modules[__name__] = _real
