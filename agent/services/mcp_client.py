"""Backward compatibility -- module moved to services/infrastructure/mcp_client.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.mcp_client")
_sys.modules[__name__] = _real
