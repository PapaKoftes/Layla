"""Tool domain modules. Each domain defines TOOLS = {"name": {...}} metadata."""

from .analysis import TOOLS as ANALYSIS_TOOLS
from .automation import TOOLS as AUTOMATION_TOOLS
from .code import TOOLS as CODE_TOOLS
from .data import TOOLS as DATA_TOOLS
from .file import TOOLS as FILE_TOOLS
from .general import TOOLS as GENERAL_TOOLS
from .geometry import TOOLS as GEOMETRY_TOOLS
from .git import TOOLS as GIT_TOOLS
from .memory import TOOLS as MEMORY_TOOLS
from .system import TOOLS as SYSTEM_TOOLS
from .web import TOOLS as WEB_TOOLS

__all__ = [
    "FILE_TOOLS",
    "GIT_TOOLS",
    "WEB_TOOLS",
    "MEMORY_TOOLS",
    "CODE_TOOLS",
    "DATA_TOOLS",
    "SYSTEM_TOOLS",
    "AUTOMATION_TOOLS",
    "ANALYSIS_TOOLS",
    "GENERAL_TOOLS",
    "GEOMETRY_TOOLS",
]
