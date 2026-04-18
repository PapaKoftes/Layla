"""Scheduling, notifications, and desktop automation tools."""

TOOLS = {
    "schedule_task": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "list_scheduled_tasks": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "cancel_task": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "send_webhook": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "send_email": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "github_issues": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "github_pr": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "discord_send": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "calendar_read": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "calendar_add_event": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "screenshot_desktop": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "click_ui": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "type_text": {"dangerous": True, "require_approval": True, "risk_level": "high"},
    "fabrication_assist_run": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
}
