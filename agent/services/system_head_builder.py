"""Backward compatibility -- module moved to services/prompts/system_head_builder.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.prompts.system_head_builder")
_sys.modules[__name__] = _real
