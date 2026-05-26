"""Backward compatibility -- module moved to services/skills/markdown_skills.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.skills.markdown_skills")
_sys.modules[__name__] = _real
