"""Backward compatibility -- module moved to services/planning/plan_step_result_models.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.plan_step_result_models")
_sys.modules[__name__] = _real
