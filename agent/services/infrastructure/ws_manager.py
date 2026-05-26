"""
WebSocket connection manager for real-time bidirectional communication.

Manages connected clients, rooms, message broadcasting, and protocol handling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Message protocol types
# ---------------------------------------------------------------------------

MSG_TYPING = "typing"  # User is typing
MSG_RESPONSE = "response"  # Agent response (streaming)
MSG_TOOL_PROGRESS = "tool_progress"  # Tool execution update
MSG_MEMORY_UPDATE = "memory_update"  # Memory changed
MSG_ERROR = "error"  # Error notification
MSG_SYSTEM = "system"  # System notification
MSG_CANCEL = "cancel"  # Cancel current operation
MSG_HEARTBEAT = "heartbeat"  # Keep-alive ping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_message(
    msg_type: str,
    data: dict,
    *,
    sender: str = "layla",
) -> dict:
    """Create a standardised WebSocket message envelope.

    Parameters
    ----------
    msg_type:
        One of the ``MSG_*`` protocol constants (e.g. ``MSG_RESPONSE``).
    data:
        Arbitrary payload dict.
    sender:
        Identifier of the message originator.

    Returns
    -------
    dict
        ``{"type": msg_type, "data": data, "sender": sender, "timestamp": ...}``
    """
    return {
        "type": msg_type,
        "data": data,
        "sender": sender,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def handle_client_message(
    message: dict,
    client_id: str,
) -> Optional[dict]:
    """Dispatch an incoming client message by its ``type`` field.

    Supported types:

    * **heartbeat** -- returns a pong message.
    * **cancel** -- logs the cancellation request and returns an ack.
    * **typing** -- logs typing indicator; no response.

    Parameters
    ----------
    message:
        Decoded JSON message from the client.  Must contain a ``type`` key.
    client_id:
        Identifier of the sending client.

    Returns
    -------
    dict | None
        A response message dict, or ``None`` when no reply is needed.
    """
    msg_type = message.get("type")

    if msg_type == MSG_HEARTBEAT:
        return create_message(MSG_HEARTBEAT, {"status": "pong"})

    if msg_type == MSG_CANCEL:
        logger.info("Cancel requested by client %s", client_id)
        return create_message(
            MSG_SYSTEM,
            {"status": "cancel_ack", "detail": "Cancellation signal received"},
        )

    if msg_type == MSG_TYPING:
        logger.debug("Client %s is typing", client_id)
        return None

    logger.warning(
        "Unknown message type '%s' from client %s",
        msg_type,
        client_id,
    )
    return create_message(
        MSG_ERROR,
        {"detail": f"Unknown message type: {msg_type}"},
    )


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Thread-safe WebSocket connection manager.

    Tracks active connections, organises clients into rooms, and provides
    methods for targeted or broadcast messaging.
    """

    def __init__(self) -> None:
        # client_id -> WebSocket
        self._connections: Dict[str, WebSocket] = {}
        # client_id -> room name
        self._client_rooms: Dict[str, str] = {}
        # client_id -> ISO-8601 connection timestamp
        self._connected_at: Dict[str, str] = {}
        # Serialises mutations so concurrent coroutines don't corrupt state
        self._lock = asyncio.Lock()

    # -- lifecycle -----------------------------------------------------------

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        room: str = "general",
    ) -> None:
        """Accept a WebSocket connection and register the client.

        Parameters
        ----------
        websocket:
            The incoming ``WebSocket`` instance.
        client_id:
            Unique identifier for this client.
        room:
            Logical room name the client joins (default ``"general"``).
        """
        await websocket.accept()
        async with self._lock:
            self._connections[client_id] = websocket
            self._client_rooms[client_id] = room
            self._connected_at[client_id] = datetime.now(
                timezone.utc
            ).isoformat()
        logger.info(
            "Client %s connected to room '%s' (%d total)",
            client_id,
            room,
            self.client_count,
        )

    async def disconnect(self, client_id: str) -> None:
        """Remove a client from all tracking structures.

        Safe to call even if *client_id* is not currently connected.

        Parameters
        ----------
        client_id:
            The client to remove.
        """
        async with self._lock:
            removed = False
            if client_id in self._connections:
                del self._connections[client_id]
                removed = True
            self._client_rooms.pop(client_id, None)
            self._connected_at.pop(client_id, None)
        if removed:
            logger.info(
                "Client %s disconnected (%d remaining)",
                client_id,
                self.client_count,
            )

    # -- send helpers --------------------------------------------------------

    async def send_personal(self, message: dict, client_id: str) -> None:
        """Send a JSON message to a single connected client.

        Parameters
        ----------
        message:
            The dict payload (will be serialised to JSON).
        client_id:
            Target client identifier.
        """
        ws = self._connections.get(client_id)
        if ws is None:
            logger.warning(
                "send_personal: client %s not connected", client_id
            )
            return
        try:
            await ws.send_json(message)
        except Exception:
            logger.exception(
                "Failed to send message to client %s; disconnecting",
                client_id,
            )
            await self.disconnect(client_id)

    async def broadcast(
        self,
        message: dict,
        room: str = "general",
        exclude: Optional[str] = None,
    ) -> None:
        """Broadcast a message to every client in *room*.

        Parameters
        ----------
        message:
            The dict payload.
        room:
            Target room name.
        exclude:
            Optional client_id to skip (e.g. the sender).
        """
        # P2-9: snapshot under lock to avoid mutation during iteration
        async with self._lock:
            targets = [
                cid
                for cid, r in self._client_rooms.items()
                if r == room and cid != exclude
            ]
        dead: List[str] = []
        for cid in targets:
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning(
                    "broadcast: client %s unreachable; marking for removal",
                    cid,
                )
                dead.append(cid)
        for cid in dead:
            await self.disconnect(cid)

    async def broadcast_all(self, message: dict) -> None:
        """Broadcast a message to **all** connected clients regardless of room.

        Parameters
        ----------
        message:
            The dict payload.
        """
        # Snapshot under lock to avoid dict-changed-size RuntimeError
        async with self._lock:
            targets = list(self._connections.items())
        dead: List[str] = []
        for cid, ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning(
                    "broadcast_all: client %s unreachable; marking for removal",
                    cid,
                )
                dead.append(cid)
        for cid in dead:
            await self.disconnect(cid)

    # -- client message dispatch ---------------------------------------------

    async def handle_client_message(
        self,
        websocket: WebSocket,
        *,
        client_id: str,
        room: str = "general",
        data: dict,
    ) -> None:
        """Dispatch an incoming client message and send response if any.

        Delegates to the module-level :func:`handle_client_message` function,
        then sends the reply back over the same WebSocket.
        """
        response = await handle_client_message(data, client_id)
        if response is not None:
            try:
                await websocket.send_json(response)
            except Exception:
                logger.warning(
                    "handle_client_message: failed to send reply to %s",
                    client_id,
                )

    # -- introspection -------------------------------------------------------

    def get_connected_clients(self) -> List[dict]:
        """Return metadata for every connected client.

        Returns
        -------
        list[dict]
            Each entry has keys ``client_id``, ``room``, and ``connected_at``.
        """
        return [
            {
                "client_id": cid,
                "room": self._client_rooms.get(cid, "unknown"),
                "connected_at": self._connected_at.get(cid, ""),
            }
            for cid in self._connections
        ]

    def get_room_members(self, room: str) -> List[str]:
        """Return the client IDs currently in *room*.

        Parameters
        ----------
        room:
            The room to query.

        Returns
        -------
        list[str]
        """
        return [
            cid for cid, r in self._client_rooms.items() if r == room
        ]

    def list_clients(self) -> List[dict]:
        """Alias for :meth:`get_connected_clients` (used by routers/ws.py)."""
        return self.get_connected_clients()

    def is_connected(self, client_id: str) -> bool:
        """Check whether *client_id* is currently connected."""
        return client_id in self._connections

    @property
    def client_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

manager = ConnectionManager()
