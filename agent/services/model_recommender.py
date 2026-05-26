"""Backward compatibility -- module moved to services/llm/model_recommender.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.model_recommender")
_sys.modules[__name__] = _real
