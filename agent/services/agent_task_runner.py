"""Backward compatibility -- module moved to services/infrastructure/agent_task_runner.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.agent_task_runner")
_sys.modules[__name__] = _real
