"""Backward compatibility -- module moved to services/workspace/file_checkpoints.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.file_checkpoints")
_sys.modules[__name__] = _real
