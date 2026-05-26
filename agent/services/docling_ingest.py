"""Backward compatibility -- module moved to services/workspace/docling_ingest.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.docling_ingest")
_sys.modules[__name__] = _real
