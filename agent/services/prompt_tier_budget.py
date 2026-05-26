"""Backward compatibility -- module moved to services/prompts/prompt_tier_budget.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.prompts.prompt_tier_budget")
_sys.modules[__name__] = _real
