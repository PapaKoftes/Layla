"""Backward compatibility -- module moved to services/workspace/doc_ingestion.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.doc_ingestion")
_sys.modules[__name__] = _real
