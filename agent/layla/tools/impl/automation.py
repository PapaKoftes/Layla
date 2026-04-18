"""Tool implementations — domain: automation."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}

_SCHEDULER = None
_SCHEDULED_JOBS: dict = {}


def _get_scheduler():
    global _SCHEDULER
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        if _SCHEDULER is None or not _SCHEDULER.running:
            _SCHEDULER = BackgroundScheduler(timezone="UTC")
            _SCHEDULER.start()
        return _SCHEDULER
    except ImportError:
        return None


def schedule_task(
    tool_name: str,
    args: dict | None = None,
    delay_seconds: float = 0,
    cron_expr: str = "",
    job_id: str = "",
) -> dict:
    """
    Schedule a tool to run in the background.
    tool_name: any registered tool name. args: dict of kwargs.
    delay_seconds: run once after N seconds. cron_expr: '*/5 * * * *' for recurring.
    Returns job_id for cancellation via cancel_task().
    """
    scheduler = _get_scheduler()
    if scheduler is None:
        return {"ok": False, "error": "apscheduler not installed: pip install apscheduler"}
    if tool_name not in TOOLS:
        return {"ok": False, "error": f"Unknown tool: {tool_name}. Use list_tools() to see available tools."}
    import uuid as _uuid
    from datetime import timedelta

    from layla.time_utils import utcnow
    jid = job_id or f"task_{tool_name}_{_uuid.uuid4().hex[:8]}"
    kw = args or {}

    def _run():
        try:
            result = TOOLS[tool_name]["fn"](**kw)
            _SCHEDULED_JOBS[jid]["last_result"] = result
            _SCHEDULED_JOBS[jid]["last_run"] = str(utcnow())[:19]
        except Exception as exc:
            if jid in _SCHEDULED_JOBS:
                _SCHEDULED_JOBS[jid]["last_error"] = str(exc)

    try:
        if cron_expr:
            from apscheduler.triggers.cron import CronTrigger
            parts = cron_expr.split()
            if len(parts) != 5:
                return {"ok": False, "error": "cron_expr must be 5 fields: 'min hour dom month dow'"}
            m, h, dom, mo, dow = parts
            trigger = CronTrigger(minute=m, hour=h, day=dom, month=mo, day_of_week=dow, timezone="UTC")
            schedule_type = f"cron: {cron_expr}"
        else:
            from apscheduler.triggers.date import DateTrigger
            run_at = utcnow() + timedelta(seconds=max(delay_seconds, 0))
            trigger = DateTrigger(run_date=run_at, timezone="UTC")
            schedule_type = f"once in {delay_seconds}s" if delay_seconds > 0 else "immediate background"
        scheduler.add_job(_run, trigger, id=jid, replace_existing=True)
        _SCHEDULED_JOBS[jid] = {"tool": tool_name, "args": kw, "schedule": schedule_type, "added_at": str(utcnow())[:19], "job_id": jid}
        return {"ok": True, "job_id": jid, "tool": tool_name, "schedule": schedule_type}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def list_scheduled_tasks() -> dict:
    """List all currently scheduled background tasks with status, next run time, and last result."""
    scheduler = _get_scheduler()
    if scheduler is None:
        return {"ok": False, "error": "apscheduler not installed"}
    jobs = []
    for job in scheduler.get_jobs():
        meta = _SCHEDULED_JOBS.get(job.id, {})
        jobs.append({"job_id": job.id, "tool": meta.get("tool", "unknown"), "args": meta.get("args", {}), "schedule": meta.get("schedule", ""), "next_run": str(job.next_run_time) if job.next_run_time else "no next run", "last_run": meta.get("last_run", "never"), "last_result": meta.get("last_result"), "last_error": meta.get("last_error")})
    return {"ok": True, "total_jobs": len(jobs), "jobs": jobs}

def cancel_task(job_id: str) -> dict:
    """Cancel a scheduled background task by job_id."""
    scheduler = _get_scheduler()
    if scheduler is None:
        return {"ok": False, "error": "apscheduler not installed"}
    try:
        scheduler.remove_job(job_id)
        meta = _SCHEDULED_JOBS.pop(job_id, {})
        return {"ok": True, "cancelled": job_id, "tool": meta.get("tool", "unknown")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def screenshot_desktop(region: list | None = None, output_path: str = "") -> dict:
    """
    Capture a screenshot of the desktop or a region [x, y, width, height].
    Uses Pillow ImageGrab or pyautogui. Returns path to saved PNG.
    """
    import tempfile as _tmp
    import time as _time
    out = output_path or str(Path(_tmp.gettempdir()) / f"layla_screen_{int(_time.time())}.png")
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]) if region else None)
        img.save(out)
        return {"ok": True, "path": out, "size": f"{img.width}x{img.height}", "method": "Pillow"}
    except ImportError:
        pass
    try:
        import pyautogui
        img = pyautogui.screenshot(region=tuple(region) if region else None)
        img.save(out)
        return {"ok": True, "path": out, "size": f"{img.width}x{img.height}", "method": "pyautogui"}
    except ImportError:
        return {"ok": False, "error": "Install Pillow or pyautogui for screenshots"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def click_ui(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    """
    Click at screen coordinates. button: left | right | middle. CAUTION: controls actual mouse.
    Requires: pip install pyautogui
    """
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return {"ok": True, "action": "click", "x": x, "y": y, "button": button, "clicks": clicks}
    except ImportError:
        return {"ok": False, "error": "pyautogui not installed: pip install pyautogui"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def type_text(text: str, interval: float = 0.03) -> dict:
    """
    Type text at current cursor position. CAUTION: types into whatever window has focus.
    interval: delay between keystrokes in seconds. Requires: pip install pyautogui
    """
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.typewrite(text, interval=max(0.01, interval))
        return {"ok": True, "action": "type", "chars_typed": len(text)}
    except ImportError:
        return {"ok": False, "error": "pyautogui not installed: pip install pyautogui"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_webhook(url: str, payload: dict, method: str = "POST") -> dict:
    """Send JSON payload to webhook URL (Slack, Discord, custom)."""
    try:
        import json as _json
        import urllib.request
        data = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:2000]
        return {"ok": True, "status": resp.status, "response": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def discord_send(content: str = "", embed: dict | None = None, webhook_url: str = "") -> dict:
    """
    Send message to Discord via webhook. Easy setup: Server Settings → Integrations → Webhooks → New.
    webhook_url: override; else reads discord_webhook_url from config or DISCORD_WEBHOOK_URL env.
    """
    url = webhook_url or __import__("os").environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        try:
            agent_dir = Path(__file__).resolve().parent.parent.parent
            sys.path.insert(0, str(agent_dir))
            import runtime_safety
            cfg = runtime_safety.load_config()
            url = cfg.get("discord_webhook_url", "") or ""
        except Exception:
            pass
    if not url:
        return {"ok": False, "error": "No webhook URL. Set discord_webhook_url in config, DISCORD_WEBHOOK_URL env, or pass webhook_url."}
    payload = {}
    if content:
        payload["content"] = content[:2000]
    if embed:
        payload["embeds"] = [{"title": embed.get("title", "")[:256], "description": (embed.get("description") or "")[:4096], "color": embed.get("color")}][:1]
    if not payload:
        return {"ok": False, "error": "Provide content or embed"}
    return send_webhook(url, payload)

def calendar_read(path: str) -> dict:
    """Read .ics calendar file. Returns events with start, end, summary."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import icalendar
        cal = icalendar.Calendar.from_ical(target.read_bytes())
        events = []
        for c in cal.walk():
            if c.name == "VEVENT":
                start = c.get("dtstart").dt if c.get("dtstart") else None
                end = c.get("dtend").dt if c.get("dtend") else None
                summary = str(c.get("summary", ""))
                events.append({"start": str(start), "end": str(end), "summary": summary})
        return {"ok": True, "path": str(target), "events": events[:50]}
    except ImportError:
        return {"ok": False, "error": "icalendar not installed: pip install icalendar"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def calendar_add_event(path: str, summary: str, start: str, end: str = "", description: str = "") -> dict:
    """Add event to .ics file. start/end: ISO or YYYY-MM-DD HH:MM. Creates file if missing."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    try:
        from datetime import datetime

        import icalendar
        cal = icalendar.Calendar()
        if target.exists():
            cal = icalendar.Calendar.from_ical(target.read_text(encoding="utf-8", errors="replace"))
        event = icalendar.Event()
        event.add("summary", summary[:200])
        event.add("dtstart", datetime.fromisoformat(start.replace("Z", "+00:00")) if "T" in start else datetime.fromisoformat(start))
        if end:
            event.add("dtend", datetime.fromisoformat(end.replace("Z", "+00:00")) if "T" in end else datetime.fromisoformat(end))
        if description:
            event.add("description", description[:500])
        cal.add_component(event)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cal.to_ical().decode("utf-8", errors="replace"), encoding="utf-8")
        return {"ok": True, "path": str(target), "summary": summary}
    except ImportError:
        return {"ok": False, "error": "icalendar not installed: pip install icalendar"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fabrication_assist_run(
    objective: str,
    session_path: str = "",
    runner_request: str = "",
    workspace_root: str = "",
) -> dict:
    """
    Deterministic Fabrication Assist kernel entry.

    Runner selection is operator-config driven:
    - Default: StubRunner
    - SubprocessJsonRunner: only when cfg.fabrication_assist.enable_subprocess is true AND runner_request == "subprocess"
    """
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    fa_cfg = cfg.get("fabrication_assist")
    if not isinstance(fa_cfg, dict):
        fa_cfg = {}

    allow_subprocess = bool(fa_cfg.get("enable_subprocess"))
    req = (runner_request or "").strip().lower()
    wants_subprocess = req == "subprocess"

    # Resolve workspace/sandbox for session file placement.
    try:
        if workspace_root:
            base = Path(workspace_root).expanduser().resolve()
        else:
            base = Path(str(_get_sandbox())).expanduser().resolve()
    except Exception:
        base = Path.cwd()

    if session_path:
        sp = Path(session_path).expanduser().resolve()
    else:
        sp = (base / ".layla" / "fabrication_assist" / "session.json").expanduser().resolve()

    if not inside_sandbox(sp):
        return {"ok": False, "error": "Outside sandbox", "path": str(sp)}

    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"cannot_create_session_dir: {e}", "path": str(sp)}

    # Select runner deterministically: stub by default, subprocess only when explicitly enabled+requested.
    runner_type = "stub"
    subprocess_requested_but_disabled = False
    try:
        from fabrication_assist.assist import assist
        from fabrication_assist.assist.runner import StubRunner, SubprocessJsonRunner

        runner = StubRunner()
        if wants_subprocess:
            if allow_subprocess:
                runner = SubprocessJsonRunner()
                runner_type = "subprocess"
            else:
                subprocess_requested_but_disabled = True

        result = assist(
            objective=objective,
            session_path=sp,
            runner=runner,
        )
        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": "fabrication_assist_invalid_result",
                "runner_type": runner_type,
                "path": str(sp),
            }
        result = dict(result)
        result.setdefault("ok", True)
        result["runner_type"] = runner_type
        result["session_path"] = str(sp)
        if subprocess_requested_but_disabled:
            result["subprocess_requested_but_disabled"] = True
        return result
    except ImportError as e:
        return {"ok": False, "error": f"fabrication_assist_not_installed: {e}", "runner_type": runner_type, "session_path": str(sp)}
    except Exception as e:
        return {"ok": False, "error": str(e), "runner_type": runner_type, "session_path": str(sp)}

def github_issues(repo_slug: str, state: str = "open", token: str = "") -> dict:
    """List GitHub issues. repo_slug: owner/repo. token: optional GITHUB_TOKEN env or param."""
    token = token or __import__("os").environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo_slug}/issues?state={state}&per_page=20"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = __import__("json").loads(resp.read().decode())
        return {"ok": True, "issues": [{"number": i["number"], "title": i["title"], "state": i["state"], "url": i["html_url"]} for i in data[:20]]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def github_pr(repo_slug: str, title: str, head: str, base: str = "main", body: str = "", token: str = "") -> dict:
    """Create a GitHub PR. token: GITHUB_TOKEN env or param."""
    token = token or __import__("os").environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"ok": False, "error": "GITHUB_TOKEN required for creating PRs"}
    import json as _json
    import urllib.request
    payload = {"title": title, "head": head, "base": base, "body": body}
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("https://api.github.com/repos/" + repo_slug + "/pulls", data=data, method="POST", headers={"Accept": "application/vnd.github.v3+json", "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pr = _json.loads(resp.read().decode())
            return {"ok": True, "number": pr.get("number"), "url": pr.get("html_url"), "title": pr.get("title")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_email(to: str, subject: str, body: str, smtp_host: str = "", smtp_port: int = 587, username: str = "", password: str = "") -> dict:
    """Send email via SMTP. Credentials from env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS."""
    import os
    host = smtp_host or os.environ.get("SMTP_HOST", "localhost")
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = username or os.environ.get("SMTP_USER", "")
    pwd = password or os.environ.get("SMTP_PASS", "")
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["To"] = to
        msg["From"] = user or "layla@local"
        with smtplib.SMTP(host, port, timeout=15) as s:
            if user and pwd:
                s.starttls()
                s.login(user, pwd)
            s.send_message(msg)
        return {"ok": True, "to": to, "subject": subject[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

