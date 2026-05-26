"""Backward compatibility -- module moved to services/skills/skill_manifest.py

This shim replaces itself in sys.modules so that ``import services.skill_manifest``
returns the canonical module.  Attribute reads *and* writes therefore operate on
the real module.
"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.skills.skill_manifest")
_sys.modules[__name__] = _real
