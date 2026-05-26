"""Backward compatibility -- module moved to services/personality/operator_quiz.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.operator_quiz")
_sys.modules[__name__] = _real
