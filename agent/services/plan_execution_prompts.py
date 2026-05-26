"""Backward compatibility -- module moved to services/planning/plan_execution_prompts.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.plan_execution_prompts")
_sys.modules[__name__] = _real
