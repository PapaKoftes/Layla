"""Cluster Pairing — one-time pairing flow for QUEEN ↔ DRONE nodes.

Flow:
1. QUEEN generates a pairing token (displayed in UI / CLI)
2. DRONE installer asks for the token
3. DRONE POSTs to QUEEN /cluster/pair with token + its own info
4. QUEEN validates token, adds drone to cluster_config.json
5. QUEEN returns cluster_secret for ongoing auth

Phase 2D of the distributed infrastructure plan.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("layla")


# ── Pairing token lifecycle ─────────────────────────────────────────────

@dataclass
class PairingToken:
    """A one-time-use pairing token for a DRONE to join the cluster."""
    token: str
    token_hash: str
    created_at: float
    expires_at: float
    used: bool = False
    used_by: str = ""


class ClusterPairing:
    """Manages the pairing flow between QUEEN and DRONE nodes.

    Only the QUEEN creates pairing tokens.  DRONEs submit them
    to prove they're authorised to join.
    """

    TOKEN_LIFETIME_SECONDS = 600  # 10 minutes

    def __init__(self):
        self._pending_tokens: dict[str, PairingToken] = {}
        self._lock = threading.Lock()

    # ── QUEEN side: generate token ───────────────────────────────────

    def generate_pairing_token(self) -> PairingToken:
        """Generate a new pairing token (QUEEN only).

        Returns the token object.  The raw ``token`` string should be
        displayed to the user (or sent via a secure channel).
        The ``token_hash`` is what we store/compare.
        """
        raw_token = secrets.token_urlsafe(24)  # ~32 chars, easy to copy
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = time.time()

        pt = PairingToken(
            token=raw_token,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + self.TOKEN_LIFETIME_SECONDS,
        )

        with self._lock:
            # Clean up expired tokens
            self._cleanup_expired()
            self._pending_tokens[token_hash] = pt

        logger.info("Generated pairing token (expires in %ds)", self.TOKEN_LIFETIME_SECONDS)
        return pt

    def validate_pairing_token(self, raw_token: str) -> tuple[bool, str]:
        """Validate a pairing token submitted by a DRONE.

        Returns (valid, reason).
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        with self._lock:
            self._cleanup_expired()
            pt = self._pending_tokens.get(token_hash)
            if pt is None:
                return False, "invalid_token"
            if pt.used:
                return False, "token_already_used"
            if time.time() > pt.expires_at:
                return False, "token_expired"
            # Mark as used
            pt.used = True
            return True, "ok"

    def _cleanup_expired(self) -> None:
        """Remove expired tokens."""
        now = time.time()
        expired = [h for h, t in self._pending_tokens.items() if now > t.expires_at + 60]
        for h in expired:
            del self._pending_tokens[h]

    # ── QUEEN side: complete pairing ─────────────────────────────────

    def accept_drone(
        self,
        drone_instance_id: str,
        drone_name: str,
        drone_address: str,
        drone_hardware_tier: str = "cpu",
    ) -> dict[str, Any]:
        """Accept a validated drone into the cluster.

        Creates a cluster secret (if not already set) and adds the
        drone to cluster_config.json.

        Returns dict with cluster_id, cluster_secret, queen_address.
        """
        from services.cluster.cluster_network import (
            NodeRole,
            Peer,
            PeerStatus,
            load_cluster_config,
            save_cluster_config,
        )

        config = load_cluster_config()

        # Ensure cluster has an ID
        if not config.get("cluster_id"):
            config["cluster_id"] = secrets.token_urlsafe(16)

        # Generate or reuse cluster secret
        cluster_secret = None
        if not config.get("cluster_secret_hash"):
            cluster_secret = secrets.token_urlsafe(32)
            config["cluster_secret_hash"] = hashlib.sha256(cluster_secret.encode()).hexdigest()
        else:
            # Need to generate a new secret for this drone (they need the raw value)
            cluster_secret = secrets.token_urlsafe(32)
            config["cluster_secret_hash"] = hashlib.sha256(cluster_secret.encode()).hexdigest()

        # Add drone to peers
        if "peers" not in config:
            config["peers"] = {}
        config["peers"][drone_instance_id] = {
            "name": drone_name,
            "role": "drone",
            "address": drone_address,
            "hardware_tier": drone_hardware_tier,
            "status": "online",
            "paired_at": datetime.now(timezone.utc).isoformat(),
        }

        save_cluster_config(config)

        # Also add to the live cluster network
        try:
            from services.cluster.cluster_network import get_cluster_network
            net = get_cluster_network()
            net.add_peer(Peer(
                instance_id=drone_instance_id,
                name=drone_name,
                role=NodeRole.DRONE,
                address=drone_address,
                hardware_tier=drone_hardware_tier,
                status=PeerStatus.ONLINE,
                last_heartbeat=time.time(),
            ))
        except Exception as e:
            logger.debug("Failed to add drone to live network: %s", e)

        # Build queen address
        queen_address = ""
        try:
            from services.infrastructure.tailscale_manager import get_connection_url
            queen_address = get_connection_url(8000) or ""
        except Exception:
            pass
        if not queen_address:
            queen_address = "http://127.0.0.1:8000"

        logger.info(
            "Paired drone %s (%s) at %s",
            drone_instance_id[:8],
            drone_name,
            drone_address,
        )

        return {
            "ok": True,
            "cluster_id": config["cluster_id"],
            "cluster_secret": cluster_secret,
            "queen_address": queen_address,
            "queen_instance_id": _get_instance_id(),
        }

    # ── DRONE side: request pairing ──────────────────────────────────

    @staticmethod
    def request_pairing(
        queen_address: str,
        pairing_token: str,
        drone_name: str = "",
        drone_hardware_tier: str = "cpu",
    ) -> dict[str, Any]:
        """Send a pairing request to a QUEEN node (DRONE side).

        Returns the response from the QUEEN (cluster_id, cluster_secret, etc).
        """
        import httpx

        # Get our own instance ID
        instance_id = _get_instance_id()

        # Get our own address (Tailscale preferred)
        drone_address = ""
        try:
            from services.infrastructure.tailscale_manager import get_connection_url
            drone_address = get_connection_url(8000) or ""
        except Exception:
            pass

        payload = {
            "pairing_token": pairing_token,
            "instance_id": instance_id,
            "name": drone_name or f"drone-{instance_id[:6]}",
            "address": drone_address,
            "hardware_tier": drone_hardware_tier,
        }

        url = f"{queen_address.rstrip('/')}/cluster/pair"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                result = resp.json()

            if result.get("ok"):
                # Save cluster info locally
                from services.cluster.cluster_network import (
                    load_cluster_config,
                    save_cluster_config,
                )
                config = load_cluster_config()
                config["cluster_enabled"] = True
                config["node_role"] = "drone"
                config["cluster_id"] = result.get("cluster_id", "")
                # Store the cluster secret hash (we receive the raw secret)
                raw_secret = result.get("cluster_secret", "")
                if raw_secret:
                    config["cluster_secret_hash"] = hashlib.sha256(raw_secret.encode()).hexdigest()
                # Add queen as a peer
                if "peers" not in config:
                    config["peers"] = {}
                queen_id = result.get("queen_instance_id", "queen")
                config["peers"][queen_id] = {
                    "name": "Queen",
                    "role": "queen",
                    "address": result.get("queen_address", queen_address),
                    "status": "online",
                    "paired_at": datetime.now(timezone.utc).isoformat(),
                }
                save_cluster_config(config)
                logger.info("Successfully paired with queen at %s", queen_address)

            return result
        except Exception as e:
            logger.error("Pairing request failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Status ───────────────────────────────────────────────────────

    def get_pending_count(self) -> int:
        """Number of pending (unused, unexpired) pairing tokens."""
        now = time.time()
        with self._lock:
            return sum(
                1
                for t in self._pending_tokens.values()
                if not t.used and now < t.expires_at
            )


# ── Helpers ──────────────────────────────────────────────────────────────

def _get_instance_id() -> str:
    """Get this node's stable instance ID."""
    try:
        from services.cluster.mdns_discovery import get_instance_id
        return get_instance_id()
    except Exception:
        import uuid
        return uuid.uuid4().hex[:12]


# ── Module-level singleton ───────────────────────────────────────────────

_pairing: ClusterPairing | None = None


def get_cluster_pairing() -> ClusterPairing:
    """Get or create the singleton ClusterPairing."""
    global _pairing
    if _pairing is None:
        _pairing = ClusterPairing()
    return _pairing
