"""Scheduling, notifications, and desktop automation tools."""

TOOLS = {
    "schedule_task": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Schedule a task to run at a specific time or on a recurring interval.",
    },
    "list_scheduled_tasks": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "List all scheduled tasks with their next run time and status.",
    },
    "cancel_task": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Cancel a previously scheduled task by its ID.",
    },
    "send_webhook": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Send a webhook POST request with a JSON payload to a specified URL.",
    },
    "send_email": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "system",
        "description": "Send an email via configured SMTP. Requires approval before sending.",
    },
    "github_issues": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "git",
        "description": "List, search, or read GitHub issues for a repository.",
    },
    "github_pr": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "git",
        "description": "Create or manage GitHub pull requests: open, comment, merge, or close.",
    },
    "discord_send": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Send a message to a Discord channel via webhook.",
    },
    "calendar_read": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Read upcoming calendar events from the configured calendar source.",
    },
    "calendar_add_event": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "planning",
        "description": "Add a new event to the calendar with title, time, duration, and description.",
    },
    "screenshot_desktop": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Take a screenshot of the desktop or a specific window and save it as an image.",
    },
    "click_ui": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Click at specified screen coordinates or on a UI element by accessibility label.",
    },
    "type_text": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Type text via keyboard simulation into the currently focused application.",
    },
    "fabrication_assist_run": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "fabrication",
        "description": "Run the fabrication assistant pipeline: validate geometry, generate toolpaths, estimate time.",
    },
}
