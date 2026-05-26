"""Backward compatibility -- module moved to services/llm/airllm_runner.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.airllm_runner")
_sys.modules[__name__] = _real
