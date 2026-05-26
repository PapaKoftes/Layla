# -*- coding: utf-8 -*-
"""
Mem0 integration -- automatic memory extraction from conversations.

Detects implicit memories in conversation turns: preferences, facts about the user,
important decisions, etc. Complements existing explicit memory saves.

Config keys:
  mem0_enabled: bool (default False)
  mem0_api_key: str (optional, for Mem0 cloud)
  mem0_provider: "local" | "cloud" (default "local")
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Cached client instance
# ---------------------------------------------------------------------------

_client_instance: Any = None
_client_cfg_hash: str | None = None


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return True if the ``mem0ai`` package can be imported."""
    try:
        import mem0ai  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _cfg_hash(cfg: dict) -> str:
    """Cheap hash of config keys relevant to client construction."""
    provider = cfg.get("mem0_provider", "local")
    api_key = cfg.get("mem0_api_key") or ""
    return f"{provider}::{api_key}"


def get_client(cfg: dict) -> Any | None:
    """Create or return a cached :class:`mem0ai.Memory` client.

    * **local** mode uses in-process memory (no API key needed).
    * **cloud** mode uses the Mem0 Platform API and requires ``mem0_api_key``.

    Returns ``None`` if the package is not installed or initialisation fails.
    """
    global _client_instance, _client_cfg_hash

    if not cfg.get("mem0_enabled", False):
        return None

    current_hash = _cfg_hash(cfg)
    if _client_instance is not None and _client_cfg_hash == current_hash:
        return _client_instance

    try:
        from mem0 import Memory  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("mem0ai package not installed -- falling back to keyword extraction")
        return None

    provider = cfg.get("mem0_provider", "local")

    try:
        if provider == "cloud":
            api_key = cfg.get("mem0_api_key") or ""
            if not api_key:
                logger.warning("mem0_provider is 'cloud' but mem0_api_key is empty")
                return None
            config = {"api_key": api_key}
            client = Memory.from_config(config)
        else:
            # Local / in-process mode -- no API key needed.
            client = Memory()

        _client_instance = client
        _client_cfg_hash = current_hash
        logger.info("Mem0 client created (provider=%s)", provider)
        return client
    except Exception as exc:
        logger.error("Failed to create Mem0 client: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Fallback keyword extraction
# ---------------------------------------------------------------------------

_PREFERENCE_RE = re.compile(
    r"(?:I\s+(?:prefer|like|love|hate|dislike|enjoy|want|need|always|never))\s+(.+)",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"(?:my\s+name\s+is|I['']?m\s+called|call\s+me)\s+([A-Z][\w\s]+)",
    re.IGNORECASE,
)
_REMEMBER_RE = re.compile(
    r"(?:remember\s+that|keep\s+in\s+mind|note\s+that|don['']?t\s+forget)\s+(.+)",
    re.IGNORECASE,
)
_FACT_RE = re.compile(
    r"(?:I\s+(?:am|work|live|study|use|have|speak))\s+(.+)",
    re.IGNORECASE,
)


def _extract_fallback(messages: list[dict]) -> list[dict]:
    """Fallback when ``mem0ai`` is not installed: simple keyword-based extraction.

    Scans user messages for patterns like "I prefer ...", "My name is ...",
    "Remember that ...", and general self-disclosures.

    Returns a list of ``{"text": str, "type": str}`` dicts.
    """
    results: list[dict] = []
    seen: set[str] = set()

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not content:
            continue

        for pattern, mem_type in [
            (_NAME_RE, "identity"),
            (_PREFERENCE_RE, "preference"),
            (_REMEMBER_RE, "instruction"),
            (_FACT_RE, "fact"),
        ]:
            for match in pattern.finditer(content):
                text = match.group(0).strip().rstrip(".")
                key = text.lower()
                if key not in seen and len(text) >= 8:
                    seen.add(key)
                    results.append({"text": text, "type": mem_type})

    return results


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def extract_memories(
    cfg: dict,
    messages: list[dict],
    *,
    user_id: str = "default",
) -> dict:
    """Extract and store memories from conversation messages.

    Takes a list of ``{"role": str, "content": str}`` dicts, passes them to
    Mem0's ``add()`` method for automatic memory extraction, and returns a
    summary of what was stored.

    Falls back to simple keyword-based extraction when ``mem0ai`` is not
    installed.

    Returns::

        {"ok": bool, "memories_extracted": int, "memories": list[dict],
         "error"?: str}
    """
    if not cfg.get("mem0_enabled", False):
        return {"ok": False, "memories_extracted": 0, "memories": [],
                "error": "mem0 is disabled in config"}

    client = get_client(cfg)

    # -- Fallback path --------------------------------------------------------
    if client is None:
        try:
            extracted = _extract_fallback(messages)
            return {
                "ok": True,
                "memories_extracted": len(extracted),
                "memories": extracted,
            }
        except Exception as exc:
            logger.error("Fallback memory extraction failed: %s", exc)
            return {"ok": False, "memories_extracted": 0, "memories": [],
                    "error": str(exc)}

    # -- Mem0 path ------------------------------------------------------------
    try:
        result = client.add(messages, user_id=user_id)
        # mem0 returns a dict with a "results" key (list of memory dicts).
        raw_memories = result.get("results", []) if isinstance(result, dict) else []
        return {
            "ok": True,
            "memories_extracted": len(raw_memories),
            "memories": raw_memories,
        }
    except Exception as exc:
        logger.error("Mem0 extract_memories failed: %s", exc)
        return {"ok": False, "memories_extracted": 0, "memories": [],
                "error": str(exc)}


def search_memories(
    cfg: dict,
    query: str,
    *,
    user_id: str = "default",
    limit: int = 10,
) -> dict:
    """Search Mem0's memory store for entries relevant to *query*.

    Returns::

        {"ok": bool, "hits": list[dict], "error"?: str}
    """
    client = get_client(cfg)
    if client is None:
        return {"ok": False, "hits": [],
                "error": "Mem0 client not available"}

    try:
        result = client.search(query, user_id=user_id, limit=limit)
        hits = result if isinstance(result, list) else result.get("results", [])
        return {"ok": True, "hits": hits}
    except Exception as exc:
        logger.error("Mem0 search_memories failed: %s", exc)
        return {"ok": False, "hits": [], "error": str(exc)}


def get_all_memories(
    cfg: dict,
    *,
    user_id: str = "default",
) -> dict:
    """Return every stored memory for *user_id*.

    Returns::

        {"ok": bool, "memories": list[dict], "count": int, "error"?: str}
    """
    client = get_client(cfg)
    if client is None:
        return {"ok": False, "memories": [], "count": 0,
                "error": "Mem0 client not available"}

    try:
        result = client.get_all(user_id=user_id)
        memories = result if isinstance(result, list) else result.get("results", [])
        return {"ok": True, "memories": memories, "count": len(memories)}
    except Exception as exc:
        logger.error("Mem0 get_all_memories failed: %s", exc)
        return {"ok": False, "memories": [], "count": 0, "error": str(exc)}


def delete_memory(cfg: dict, memory_id: str) -> dict:
    """Delete a specific memory by its ID.

    Returns::

        {"ok": bool, "error"?: str}
    """
    client = get_client(cfg)
    if client is None:
        return {"ok": False, "error": "Mem0 client not available"}

    try:
        client.delete(memory_id)
        return {"ok": True}
    except Exception as exc:
        logger.error("Mem0 delete_memory failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_status(cfg: dict | None = None) -> dict:
    """Return an overview of the Mem0 integration state.

    Returns::

        {"enabled": bool, "available": bool, "provider": str,
         "memory_count": int}
    """
    if cfg is None:
        cfg = {}

    enabled = cfg.get("mem0_enabled", False)
    available = is_available()
    provider = cfg.get("mem0_provider", "local")
    memory_count = 0

    if enabled and available:
        try:
            client = get_client(cfg)
            if client is not None:
                result = client.get_all()
                if isinstance(result, list):
                    memory_count = len(result)
                elif isinstance(result, dict):
                    memory_count = len(result.get("results", []))
        except Exception:
            pass  # Non-critical; count stays 0

    return {
        "enabled": enabled,
        "available": available,
        "provider": provider,
        "memory_count": memory_count,
    }
