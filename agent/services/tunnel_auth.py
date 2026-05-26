"""Backward compatibility -- module moved to services/governance/tunnel_auth.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.governance.tunnel_auth")
_sys.modules[__name__] = _real
