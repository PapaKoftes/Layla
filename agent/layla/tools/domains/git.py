"""Git version control tools."""

TOOLS = {
    "git_status": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_diff": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_log": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_branch": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_add": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_commit": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_push": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_pull": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_stash": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_revert": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_clone": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "git_blame": {"dangerous": False, "require_approval": False, "risk_level": "low"},
}
