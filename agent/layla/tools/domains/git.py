"""Git version control tools."""

TOOLS = {
    "git_status": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "git_diff": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "git_log": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "git_branch": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "git_add": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_commit": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_push": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_pull": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_stash": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_revert": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_clone": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "git_blame": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "git_worktree_add": {"fn_key": "git_worktree_add", "dangerous": True, "require_approval": True, "risk_level": "high"},
    "git_worktree_remove": {"fn_key": "git_worktree_remove", "dangerous": True, "require_approval": True, "risk_level": "high"},
}
