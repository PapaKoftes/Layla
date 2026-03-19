"""Shell, pip, env, Docker, and system utilities."""

TOOLS = {
    "shell": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "shell_session_start": {"dangerous": True, "require_approval": True, "risk_level": "high", "fn_key": "shell_session_start"},
    "shell_session_manage": {"dangerous": False, "require_approval": False, "risk_level": "medium", "fn_key": "shell_session_manage"},
    "pip_list": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "pip_install": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "env_info": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "disk_usage": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "process_list": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "check_port": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "check_ci": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "docker_ps": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "docker_run": {"dangerous": True, "require_approval": True, "risk_level": "high"},
}
