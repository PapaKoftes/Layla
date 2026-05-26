"""
Config migrator — detects old config format and auto-upgrades.

Handles:
  - New keys from Phases 1-8 (adds with defaults)
  - Renamed keys (migrates values)
  - Deprecated keys (warns and removes)

Usage:
    from services.config_migrator import migrate_config
    cfg, changes = migrate_config(cfg)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------

# Keys renamed from old → new (value is carried over)
_RENAMES: dict[str, str] = {
    # Example: "old_key_name": "new_key_name",
}

# Keys deprecated (will be removed with a warning)
_DEPRECATED: set[str] = {
    "knowledge_unrestricted",   # B4 from blueprint — was dead config flag
    "anonymous_access",         # B4 from blueprint — was dead config flag
}

# New keys with their defaults (added if missing)
# NOTE: Defaults here MUST match runtime_safety.py defaults dict.
# Secrets/API-keys use None (not ""), booleans default to False (opt-in).
_NEW_DEFAULTS: dict[str, Any] = {
    # ── LiteLLM Gateway (Phase 1) ────────────────────────────────────
    "litellm_enabled": False,
    "litellm_default_model": None,
    "litellm_fallback_chain": [],
    "litellm_api_keys": {},
    "litellm_timeout_seconds": 120,
    "litellm_max_retries": 2,
    # ── Discord (Phase 2) ────────────────────────────────────────────
    "discord_bot_autostart": False,
    "discord_bot_token": None,
    "discord_bot_default_aspect": None,
    # ── Tunnel auth & audit (Phase 3) ────────────────────────────────
    "tunnel_token_hash": None,
    "tunnel_token_created_at": None,
    "tunnel_token_ttl_hours": 0,         # 0 = never expires
    "tunnel_ip_allowlist": [],
    "tunnel_audit_enabled": False,       # activates when remote_enabled is True
    "tunnel_audit_retention_days": 90,
    "tailscale_enabled": False,
    "tailscale_auth_key": None,
    # ── Search backends (Phase 5) ────────────────────────────────────
    "search_backend": "auto",
    "elasticsearch_enabled": False,
    "elasticsearch_url": None,
    "elasticsearch_index_prefix": "layla",
    "elasticsearch_api_key": None,
    "meilisearch_enabled": False,
    "meilisearch_url": "http://localhost:7700",
    "meilisearch_api_key": None,
    "meilisearch_index": "layla-learnings",
    # ── Web crawling (Phase 6A) ──────────────────────────────────────
    "crawler_backend": "auto",
    "firecrawl_api_key": None,
    "firecrawl_api_url": "https://api.firecrawl.dev",
    "crawl4ai_enabled": False,           # opt-in like all other integrations
    # ── Document ingestion (Phase 6B) ────────────────────────────────
    "docling_enabled": False,
    "docling_chunk_size": 1000,
    "docling_overlap": 200,
    # ── Vector store (Phase 6C) ──────────────────────────────────────
    "vector_backend": "chroma",
    "qdrant_url": "http://localhost:6333",
    "qdrant_api_key": None,
    "qdrant_collection": "layla-memories",
    # ── Memory extraction (Phase 6D) ─────────────────────────────────
    "mem0_enabled": False,
    "mem0_api_key": None,
    "mem0_provider": "local",
}


def migrate_config(cfg: dict) -> tuple[dict, list[str]]:
    """Migrate a config dict to the latest schema.

    Returns ``(updated_cfg, changes)`` where *changes* is a list of
    human-readable descriptions of what was migrated.
    """
    changes: list[str] = []
    cfg = dict(cfg)  # don't mutate the original

    # 1. Rename old keys
    for old, new in _RENAMES.items():
        if old in cfg and new not in cfg:
            cfg[new] = cfg.pop(old)
            changes.append(f"renamed '{old}' → '{new}'")
        elif old in cfg:
            # New key already exists, just remove old
            cfg.pop(old)
            changes.append(f"removed stale '{old}' ('{new}' already set)")

    # 2. Remove deprecated keys
    for key in _DEPRECATED:
        if key in cfg:
            cfg.pop(key)
            changes.append(f"removed deprecated '{key}'")

    # 3. Add missing new keys with defaults
    for key, default in _NEW_DEFAULTS.items():
        if key not in cfg:
            cfg[key] = default
            changes.append(f"added '{key}' = {default!r}")

    if changes:
        logger.info("config_migrator: applied %d migration(s)", len(changes))
        for c in changes:
            logger.debug("config_migrator: %s", c)

    return cfg, changes


def get_migration_status(cfg: dict) -> dict:
    """Check how many migrations would be needed without applying them.

    Returns ``{"needs_migration": bool, "pending_changes": int, "changes": list[str]}``.
    """
    _, changes = migrate_config(cfg)
    return {
        "needs_migration": len(changes) > 0,
        "pending_changes": len(changes),
        "changes": changes,
    }


def get_current_version() -> str:
    """Return the current config schema version."""
    return "2.1.0"  # Phases 1-8
