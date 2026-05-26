"""Backward compatibility -- module moved to services/memory/conversation_entity_extractor.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.conversation_entity_extractor")
_sys.modules[__name__] = _real
