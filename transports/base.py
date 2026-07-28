"""
Unified transport layer for Layla. Single call_layla() with config and error handling.
Discord, Slack, Telegram use this as thin adapters.

Inbound security (optional): optional allowlist + optional /pair <secret>.
See transports/README.md and docs/ALIGNMENT_NOTE.md.

Security posture for transport-originated turns (Slack/Telegram/Discord):
  * They are UNTRUSTED input. ``TransportAdapter`` FORCES ``allow_write=allow_run=False``
    on every agent call — a remote chat can never get filesystem-write or code-exec.
  * An inbound allowlist / pairing gate (``check_transport_inbound``) runs before the
    agent is ever called; a non-allowlisted sender is refused with no agent invocation.
  * Tokens and config are never echoed back to the chat — replies carry only agent text.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

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
            # constant-time compare so the shared pairing secret can't be recovered by timing
            if hmac.compare_digest(str(m.group(1)), str(secret)):
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
    """Async HTTP POST to Layla /agent (httpx). For Discord, Slack, Telegram.

    httpx is a first-class Layla core dependency, so the async run path has no
    extra install (aiohttp was previously used but is declared nowhere).
    """
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
        import httpx
    except Exception as e:  # httpx is core; degrade rather than crash the transport
        logger.exception("httpx unavailable for transport call")
        return f"Could not reach Layla: {e}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                return f"Layla API error: {resp.status_code}"
            data = resp.json()
        text = data.get("response", data.get("text", str(data)))
        return (text or "")[:max_response_chars]
    except httpx.TimeoutException:
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
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=timeout)
            data = resp.json()
            if resp.status_code != 200:
                return {"ok": False, "error": data.get("error", f"HTTP {resp.status_code}")}
            return data if isinstance(data, dict) else {"ok": False, "error": str(data)}
    except Exception as e:
        logger.exception("save_learning_async failed")
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Base adapter — the shared, first-class inbound pipeline for chat transports.
#
# Every transport (Slack, Telegram, Discord) drives its inbound turns through a
# single ``TransportAdapter`` so security and history behave identically:
#
#     message-in  ->  inbound security gate  ->  run the agent  ->  reply-out
#                     (allowlist / pairing)      (allow_write =
#                                                  allow_run = FORCED False)
#
# Conversation history is bounded and keyed by chat id, so each chat gets its
# own short rolling context without any cross-chat bleed. History lives only in
# this process (in-memory) and is passed to the agent as ``context``; each agent
# call still gets a fresh server-side conversation id, so nothing leaks between
# chats even on a shared Layla server.
# ---------------------------------------------------------------------------

DEFAULT_ASPECT = "morrigan"

# Public type aliases for the pluggable run path (handy for tests / DI).
AsyncRunner = Callable[..., Awaitable[str]]
SyncRunner = Callable[..., str]


@dataclass
class InboundResult:
    """Outcome of one inbound turn through :class:`TransportAdapter`.

    ``allowed`` is False when the security gate refused the sender (``reply`` then
    holds the user-facing denial / pairing message, or None to stay silent).
    ``ran_agent`` is True only when the agent was actually invoked.
    """

    allowed: bool
    reply: str | None
    ran_agent: bool = False


class TransportAdapter:
    """Shared inbound pipeline for Layla chat transports.

    Contract
    --------
    * ``gate(user_id, text)`` runs the SHARED inbound security policy
      (:func:`check_transport_inbound`): allowlist + optional ``/pair`` handshake.
      A non-allowlisted / unpaired sender is refused *before* the agent is called.
    * ``run_async`` / ``run_sync`` invoke the agent for an already-gated turn with
      ``allow_write=allow_run=False`` **forced** — transport turns are untrusted and
      can never obtain filesystem-write or code-execution, mirroring the router's
      fail-closed stance. There is deliberately no parameter to raise them.
    * ``handle_inbound_async`` / ``handle_inbound_sync`` are the convenience
      one-shots: gate, then (if allowed) run and record history.
    * Conversation history is bounded (``history_turns``) and keyed by chat id.

    The run path defaults to the localhost Layla HTTP API
    (:func:`call_layla_async` / :func:`call_layla_sync`); a custom ``async_runner`` /
    ``sync_runner`` may be injected (used by tests to assert the forced flags).
    """

    def __init__(
        self,
        platform: str,
        *,
        aspect_id: str = DEFAULT_ASPECT,
        max_response_chars: int = 4000,
        timeout: int = 60,
        history_turns: int = 6,
        async_runner: AsyncRunner | None = None,
        sync_runner: SyncRunner | None = None,
    ) -> None:
        self.platform = (platform or "").strip().lower()
        if not self.platform:
            raise ValueError("platform is required")
        self.aspect_id = (aspect_id or DEFAULT_ASPECT).strip() or DEFAULT_ASPECT
        self.max_response_chars = int(max_response_chars)
        self.timeout = int(timeout)
        self.history_turns = max(0, int(history_turns))
        self._async_runner = async_runner
        self._sync_runner = sync_runner
        self._history: dict[str, deque[tuple[str, str]]] = {}
        self._history_lock = threading.RLock()

    # -- conversation history keyed by chat id ------------------------------
    def conversation_key(self, chat_id: Any) -> str:
        """Stable per-chat key, namespaced by platform (e.g. ``telegram:12345``)."""
        return f"{self.platform}:{str(chat_id).strip()}"

    def render_context(self, chat_id: Any) -> str:
        """Recent turns for ``chat_id`` rendered as agent context (may be empty)."""
        if self.history_turns <= 0:
            return ""
        key = str(chat_id).strip()
        with self._history_lock:
            turns = list(self._history.get(key, ()))
        if not turns:
            return ""
        lines: list[str] = []
        for user_text, reply_text in turns:
            lines.append(f"User: {user_text}")
            lines.append(f"Layla: {reply_text}")
        return "\n".join(lines)

    def _record_turn(self, chat_id: Any, user_text: str, reply_text: str) -> None:
        if self.history_turns <= 0:
            return
        key = str(chat_id).strip()
        with self._history_lock:
            dq = self._history.get(key)
            if dq is None:
                dq = deque(maxlen=self.history_turns)
                self._history[key] = dq
            dq.append((user_text, reply_text))

    def reset(self, chat_id: Any | None = None) -> None:
        """Drop history for one chat, or all chats when ``chat_id`` is None."""
        with self._history_lock:
            if chat_id is None:
                self._history.clear()
            else:
                self._history.pop(str(chat_id).strip(), None)

    # -- shared security gate ------------------------------------------------
    def gate(self, user_id: Any, text: str | None) -> tuple[bool, str | None]:
        """Run the shared inbound policy. See :func:`check_transport_inbound`."""
        return check_transport_inbound(self.platform, str(user_id), text)

    # -- run path (allow_write / allow_run FORCED False) ---------------------
    async def run_async(self, chat_id: Any, text: str) -> str:
        """Run the agent for an already-gated turn; record history. Never grants write/run."""
        runner = self._async_runner or call_layla_async
        reply = await runner(
            text,
            context=self.render_context(chat_id),
            allow_write=False,  # FORCED: a transport turn is untrusted input
            allow_run=False,  # FORCED: ...and must never execute code
            aspect_id=self.aspect_id,
            max_response_chars=self.max_response_chars,
            timeout=self.timeout,
        )
        reply = reply or ""
        self._record_turn(chat_id, text, reply)
        return reply

    def run_sync(self, chat_id: Any, text: str) -> str:
        """Sync counterpart of :meth:`run_async` (for sync handlers, e.g. slack_bolt)."""
        runner = self._sync_runner or call_layla_sync
        reply = runner(
            text,
            context=self.render_context(chat_id),
            allow_write=False,  # FORCED
            allow_run=False,  # FORCED
            aspect_id=self.aspect_id,
            max_response_chars=self.max_response_chars,
            timeout=self.timeout,
        )
        reply = reply or ""
        self._record_turn(chat_id, text, reply)
        return reply

    # -- convenience one-shots (gate + run) ----------------------------------
    async def handle_inbound_async(self, *, chat_id: Any, user_id: Any, text: str | None) -> InboundResult:
        allowed, deny = self.gate(user_id, text)
        if not allowed:
            return InboundResult(allowed=False, reply=deny, ran_agent=False)
        reply = await self.run_async(chat_id, text or "")
        return InboundResult(allowed=True, reply=reply, ran_agent=True)

    def handle_inbound_sync(self, *, chat_id: Any, user_id: Any, text: str | None) -> InboundResult:
        allowed, deny = self.gate(user_id, text)
        if not allowed:
            return InboundResult(allowed=False, reply=deny, ran_agent=False)
        reply = self.run_sync(chat_id, text or "")
        return InboundResult(allowed=True, reply=reply, ran_agent=True)
