"""Backward compatibility -- module moved to services/tools/tool_output_validator.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.tools.tool_output_validator")
_sys.modules[__name__] = _real
