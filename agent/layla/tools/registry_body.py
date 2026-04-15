"""Tool implementations aggregated from :mod:`layla.tools.impl` submodules."""
from __future__ import annotations

from typing import Any

# Injected by layla.tools.registry after TOOLS is assembled.
TOOLS: dict[str, Any] = {}

import layla.tools.impl.analysis as analysis
import layla.tools.impl.automation as automation
import layla.tools.impl.code as code
import layla.tools.impl.data as data
import layla.tools.impl.file_ops as file_ops
import layla.tools.impl.general as general
import layla.tools.impl.geometry as geometry
import layla.tools.impl.git as git
import layla.tools.impl.memory as memory
import layla.tools.impl.system as system
import layla.tools.impl.web as web

_IMPL_MODULES = (
    file_ops,
    git,
    system,
    code,
    web,
    memory,
    data,
    analysis,
    automation,
    geometry,
    general,
)

for _m in _IMPL_MODULES:
    for _name in dir(_m):
        if _name.startswith("_"):
                continue
        _obj = getattr(_m, _name)
        if callable(_obj):
            globals()[_name] = _obj
