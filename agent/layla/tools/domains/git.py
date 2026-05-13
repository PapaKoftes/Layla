"""Git version control tools."""

TOOLS = {
    "git_status": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "git",
        "description": "Show the working tree status: staged, unstaged, and untracked files.",
    },
    "git_diff": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "git",
        "description": "Show changes between commits, staging area, and working tree as a unified diff.",
    },
    "git_log": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "git",
        "description": "Show commit history with hashes, authors, dates, and messages.",
    },
    "git_branch": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "git",
        "description": "List, create, or switch branches. Shows current branch and tracking info.",
    },
    "git_add": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "git",
        "description": "Stage files for the next commit. Accepts specific paths or patterns.",
    },
    "git_commit": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "git",
        "description": "Create a new commit from staged changes with a descriptive message.",
    },
    "git_push": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "git",
        "description": "Push local commits to the remote repository.",
    },
    "git_pull": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "git",
        "description": "Fetch and merge changes from the remote branch into the current branch.",
    },
    "git_stash": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "git",
        "description": "Temporarily save uncommitted changes to a stash stack, or restore them.",
    },
    "git_revert": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "git",
        "description": "Create a new commit that undoes the changes from a previous commit.",
    },
    "git_clone": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "git",
        "description": "Clone a remote repository to a local directory.",
    },
    "git_blame": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "git",
        "description": "Show which commit last modified each line of a file, with author and date.",
    },
    "git_worktree_add": {
        "fn_key": "git_worktree_add",
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "git",
        "description": "Create a new git worktree for parallel branch work without switching.",
    },
    "git_worktree_remove": {
        "fn_key": "git_worktree_remove",
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "git",
        "description": "Remove a previously created git worktree and clean up its directory.",
    },
}
