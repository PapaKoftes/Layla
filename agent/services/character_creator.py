"""Backward compatibility -- module moved to services/personality/character_creator.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.character_creator")
_sys.modules[__name__] = _real
