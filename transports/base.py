"""
Unified transport layer for Layla. Single call_layla() with config and error handling.
Discord, Slack, Telegram use this as thin adapters.

Inbound security (OpenClaw-style): optional allowlist + optional /pair <secret>.
See transports/README.md and docs/OPENCLAW_ALIGNMENT.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla.transport")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PAIR_LOCK = threading.RLock()  # nested save inside check_transport_inbound
_PAIR_CMD = re.compile(r"^/pair\s+(\S+)\s*$", re.IGNORECASE | re.DOTALL)

_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))


class LaylaTransportError(Exception):
    """Raised when Layla API call fails."""


def get_agent_url() -> str:
    """Layla API base URL. Env LAYLA_API_URL or runtime_config layla_api_url."""
    url = os.environ.get("LAYLA_API_URL", "").strip()
    if url:
        return url.rstrip("/")
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        url = (cfg.get("layla_api_url") or cfg.get("agent_url") or "").strip()
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:8000"


def get_transport_config() -> dict[str, Any]:
    """Return config dict: agent_url, discord_bot_token, slack_bot_token, slack_app_token, telegram_bot_token."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    return {
        "agent_url": get_agent_url(),
        "discord_bot_token": os.environ.get("DISCORD_BOT_TOKEN") or cfg.get("discord_bot_token") or "",
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN") or cfg.get("slack_bot_token") or "",
        "slack_app_token": os.environ.get("SLACK_APP_TOKEN") or cfg.get("slack_app_token") or "",
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token") or "",
    }


def _paired_ids_path() -> Path:
    return _REPO_ROOT / ".layla_transport_paired.json"


def _parse_id_list(raw: str) -> set[str]:
    """Comma- or whitespace-separated ids, case-sensitive; empty -> empty set."""
    if not raw or not str(raw).strip():
        return set()
    parts = re.split(r"[\s,]+", str(raw).strip())
    return {p.strip() for p in parts if p.strip()}


def get_inbound_transport_security() -> dict[str, Any]:
    """
    Allowlist + pairing policy for Slack/Telegram/Discord transports.

    Env (override config for allowlist):
      LAYLA_TRANSPORT_ALLOWLIST — comma-separated user ids (and/or platform:id)
      LAYLA_TRANSPORT_PAIRING_SECRET — if set, new users must send `/pair <secret>` once
    Config (runtime_safety.load_config):
      transport_allowlist — same as env if env empty
      transport_require_allowlist — if true, deny all when neither allowlist nor pairing secret is configured
    """
    allow_env = os.environ.get("LAYLA_TRANSPORT_ALLOWLIST", "").strip()
    secret = os.environ.get("LAYLA_TRANSPORT_PAIRING_SECRET", "").strip()
    require = False
    allow_cfg = ""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        if not allow_env:
            allow_cfg = (cfg.get("transport_allowlist") or "").strip()
        require = bool(cfg.get("transport_require_allowlist", False))
    except Exception:
        cfg = {}
    allow_raw = allow_env or allow_cfg
    allowlist = _parse_id_list(allow_raw)
    misconfigured = require and not allowlist and not secret
    return {
        "allowlist": allowlist,
        "pairing_secret": secret,
        "transport_require_allowlist": require,
        "misconfigured": misconfigured,
    }


def _load_paired_ids() -> set[str]:
    path = _paired_ids_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x).strip() for x in data if str(x).strip()}
    except Exception as e:
        logger.warning("Could not read paired transport ids: %s", e)
    return set()


def _save_paired_ids(ids: set[str]) -> None:
    path = _paired_ids_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _PAIR_LOCK:
            path.write_text(json.dumps(sorted(ids), indent=0), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not save paired transport ids: %s", e)


def _transport_keys(platform: str, user_id: str) -> set[str]:
    uid = str(user_id).strip()
    plat = platform.strip().lower()
    return {uid, f"{plat}:{uid}"}


def _is_on_allowlist(allowlist: set[str], platform: str, user_id: str) -> bool:
    if not allowlist:
        return False
    keys = _transport_keys(platform, user_id)
    return bool(allowlist & keys)


def _is_paired(platform: str, user_id: str, paired: set[str]) -> bool:
    keys = _transport_keys(platform, user_id)
    return bool(keys & paired)


def check_transport_inbound(
    platform: str,
    user_id: str,
    text: str | None,
) -> tuple[bool, str | None]:
    """
    Gate before forwarding user text to Layla.

    Returns:
      (True, None) — OK to call Layla
      (False, msg) — do not call Layla; send msg to user (denial or pairing success)

    Pairing: when LAYLA_TRANSPORT_PAIRING_SECRET is set, user sends `/pair <secret>`;
    on success we persist `platform:user_id` and reply with a short confirmation.
    """
    sec = get_inbound_transport_security()
    if sec["misconfigured"]:
        logger.error(
            "transport_require_allowlist is true but no allowlist or pairing secret; denying all inbound"
        )
        return (
            False,
            "Transport security is misconfigured (require allowlist but no allowlist or pairing secret).",
        )

    plat = platform.strip().lower()
    uid = str(user_id).strip()
    allowlist: set[str] = sec["allowlist"]
    secret: str = sec["pairing_secret"]
    paired = _load_paired_ids()

    # Explicit allowlist match always wins
    if _is_on_allowlist(allowlist, plat, uid):
        return True, None

    if _is_paired(plat, uid, paired):
        return True, None

    # Pairing handshake (only when secret configured)
    if secret and text is not None:
        m = _PAIR_CMD.match(text.strip())
        if m:
            if m.group(1) == secret:
                key = f"{plat}:{uid}"
                with _PAIR_LOCK:
                    cur = _load_paired_ids()
                    cur.add(key)
                    _save_paired_ids(cur)
                return (False, "Paired. You can chat now.")
            return (False, "Invalid pairing code.")

    # Locked down: need allowlist or prior pairing
    if allowlist or secret:
        if secret and not allowlist:
            return (
                False,
                "Unauthorized. Send `/pair <code>` once (operator sets LAYLA_TRANSPORT_PAIRING_SECRET).",
            )
        return (
            False,
            "Unauthorized. Ask the operator to add your user id to LAYLA_TRANSPORT_ALLOWLIST "
            "or complete pairing.",
        )

    return True, None


def call_layla_sync(
    message: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    aspect_id: str = "morrigan",
    timeout: int = 60,
    max_response_chars: int = 4000,
    persona_focus: str = "",
) -> str:
    """Sync HTTP POST to Layla /agent. Uses urllib (no aiohttp)."""
    url = get_agent_url() + "/agent"
    payload = {
        "message": message,
        "context": context,
        "workspace_root": workspace_root or str(Path.home()),
        "allow_write": allow_write,
        "allow_run": allow_run,
        "aspect_id": aspect_id,
    }
    pf = (persona_focus or "").strip()
    if pf:
        payload["persona_focus"] = pf
    try:
        import urllib.request
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = data.get("response", data.get("text", str(data)))
        return (text or "")[:max_response_chars]
    except (TimeoutError, OSError) as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            return "Layla took too long to respond."
        logger.exception("Layla API call failed")
        return f"Could not reach Layla: {e}"
    except Exception as e:
        logger.exception("Layla API call failed")
        return f"Could not reach Layla: {e}"


async def call_layla_async(
    message: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    aspect_id: str = "morrigan",
    timeout: int = 60,
    max_response_chars: int = 4000,
    persona_focus: str = "",
) -> str:
    """Async HTTP POST to Layla /agent. For Discord, Slack, Telegram."""
    url = get_agent_url() + "/agent"
    payload = {
        "message": message,
        "context": context,
        "workspace_root": workspace_root or str(Path.home()),
        "allow_write": allow_write,
        "allow_run": allow_run,
        "aspect_id": aspect_id,
    }
    pf = (persona_focus or "").strip()
    if pf:
        payload["persona_focus"] = pf
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return f"Layla API error: {resp.status}"
                data = await resp.json()
        text = data.get("response", data.get("text", str(data)))
        return (text or "")[:max_response_chars]
    except asyncio.TimeoutError:
        return "Layla took too long to respond."
    except Exception as e:
        logger.exception("Layla API call failed")
        return f"Could not reach Layla: {e}"


async def save_learning_async(
    content: str,
    kind: str = "fact",
    tags: str = "",
    timeout: int = 30,
) -> dict:
    """POST /learn/ — explicit operator notes from transports (e.g. Discord /note)."""
    url = get_agent_url().rstrip("/") + "/learn/"
    payload: dict = {"content": content, "type": kind}
    if (tags or "").strip():
        payload["tags"] = tags.strip()[:500]
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                data = await resp.json()
                if resp.status != 200:
                    return {"ok": False, "error": data.get("error", f"HTTP {resp.status}")}
                return data if isinstance(data, dict) else {"ok": False, "error": str(data)}
    except Exception as e:
        logger.exception("save_learning_async failed")
        return {"ok": False, "error": str(e)}
