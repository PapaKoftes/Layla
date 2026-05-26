"""Backward compatibility -- module moved to services/planning/plan_step_governance.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.planning.plan_step_governance")
_sys.modules[__name__] = _real
