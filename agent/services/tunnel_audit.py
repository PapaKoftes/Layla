"""Backward compatibility -- module moved to services/governance/tunnel_audit.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.governance.tunnel_audit")
_sys.modules[__name__] = _real
