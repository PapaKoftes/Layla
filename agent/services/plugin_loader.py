"""Backward compatibility -- module moved to services/skills/plugin_loader.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.skills.plugin_loader")
_sys.modules[__name__] = _real
