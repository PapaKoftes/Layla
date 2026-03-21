"""
Structured geometry programs (GenCAD-style command sequences) with pluggable backends.

Validate with `parse_program`, execute with `execute_program` from `executor`.
"""

from __future__ import annotations

from layla.geometry.executor import execute_program, list_framework_status
from layla.geometry.schema import GeometryProgram, parse_program, validate_program_dict

GEOMETRY_STACK_VERSION = "1.0.0"

__all__ = [
    "GEOMETRY_STACK_VERSION",
    "GeometryProgram",
    "parse_program",
    "validate_program_dict",
    "execute_program",
    "list_framework_status",
]
