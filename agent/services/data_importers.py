"""Backward compatibility -- module moved to services/infrastructure/data_importers.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.data_importers")
_sys.modules[__name__] = _real
