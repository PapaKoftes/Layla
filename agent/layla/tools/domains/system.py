"""Shell, pip, env, Docker, and system utilities."""

TOOLS = {
    "shell": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Execute an arbitrary shell command and return stdout, stderr, and exit code.",
    },
    "shell_session_start": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "fn_key": "shell_session_start",
        "category": "system",
        "description": "Start a persistent shell session for running multiple sequential commands.",
    },
    "shell_session_manage": {
        "dangerous": False, "require_approval": False, "risk_level": "medium",
        "fn_key": "shell_session_manage",
        "category": "system",
        "description": "Send a command to or close an existing shell session.",
    },
    "pip_list": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List installed Python packages with their versions.",
    },
    "pip_install": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Install a Python package via pip. Supports version constraints and extras.",
    },
    "env_info": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Show system environment: Python version, OS, CPU, RAM, GPU, and key paths.",
    },
    "disk_usage": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Show disk usage for a path: total, used, free space, and largest subdirectories.",
    },
    "process_list": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List running processes with PID, name, CPU, and memory usage.",
    },
    "check_port": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Check if a network port is open or in use on localhost or a remote host.",
    },
    "check_ci": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Check the status of CI/CD pipelines for the current repository.",
    },
    "docker_ps": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List running Docker containers with image, status, and port mappings.",
    },
    "docker_run": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Run a Docker container with specified image, volumes, ports, and environment.",
    },
}
