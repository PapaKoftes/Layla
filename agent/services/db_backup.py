"""Backward compatibility -- module moved to services/infrastructure/db_backup.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.db_backup")
_sys.modules[__name__] = _real
