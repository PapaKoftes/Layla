from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from layla.tools.sandbox_core import inside_sandbox


class PolicyViolation(Exception):
    pass


_DEFAULT_TIER0 = (
    "read_file",
    "list_dir",
    "grep_code",
    "glob_files",
    "file_info",
    "python_ast",
    "workspace_map",
    "search_codebase",
)


_PATH_ARG_KEYS = frozenset(
    {
        "path",
        "paths",
        "root",
        "repo",
        "cwd",
        "workspace_root",
        "directory",
    }
)


@dataclass(frozen=True)
class Policy:
    tool_allowlist: frozenset[str]
    allow_network: bool = False

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Policy":
        raw = cfg.get("autonomous_tool_allowlist")
        if isinstance(raw, (list, tuple, set)):
            tools = [str(x).strip() for x in raw if str(x).strip()]
        else:
            tools = list(_DEFAULT_TIER0)
        return cls(tool_allowlist=frozenset(tools), allow_network=bool(cfg.get("autonomous_allow_network", False)))

    def is_tool_allowed(self, tool: str) -> bool:
        return bool(tool) and tool in self.tool_allowlist

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args, dict):
            raise PolicyViolation("args_not_dict")
        for k, v in args.items():
            if k in _PATH_ARG_KEYS:
                self._validate_path_value(v)

    def _validate_path_value(self, v: Any) -> None:
        if v is None:
            return
        if isinstance(v, (list, tuple)):
            for x in v:
                self._validate_path_value(x)
            return
        if isinstance(v, dict):
            for x in v.values():
                self._validate_path_value(x)
            return
        p = str(v).strip()
        if not p:
            return
        # inside_sandbox resolves and guards traversal; do not prefix-check.
        try:
            if not inside_sandbox(Path(p)):
                raise PolicyViolation(f"outside_sandbox:{p}")
        except PolicyViolation:
            raise
        except Exception:
            # Defensive: if path resolution fails, reject.
            raise PolicyViolation(f"invalid_path:{p}")

    def validate_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        if not self.is_tool_allowed(tool):
            raise PolicyViolation("tool_not_allowed")
        self.validate_args(args)


def tier0_default() -> frozenset[str]:
    return frozenset(_DEFAULT_TIER0)

