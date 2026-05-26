"""Backward compatibility -- module moved to services/user/onboarding_interview.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.user.onboarding_interview")
_sys.modules[__name__] = _real
