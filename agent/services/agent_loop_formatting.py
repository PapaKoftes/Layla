"""Backward compatibility -- module moved to services/infrastructure/agent_loop_formatting.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.agent_loop_formatting")
_sys.modules[__name__] = _real
