"""
WebSocket router — /ws endpoint for real-time bidirectional communication.

Uses services.ws_manager.ConnectionManager for connection lifecycle management.
"""
from __future__ import annotations

import json
import logging
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.ws_manager import manager as ws_manager

logger = logging.getLogger("layla")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_main(websocket: WebSocket):
    """Main WebSocket endpoint for bidirectional communication.

    Query params:
        client_id — optional identifier for the client (defaults to a UUID).
        room      — optional room/channel name (defaults to "general").

    On connect the server sends a welcome message.  The endpoint then loops,
    receiving JSON messages and dispatching them through the connection
    manager.  Disconnects and unexpected errors are handled gracefully.
    """
    client_id: str = websocket.query_params.get("client_id", str(uuid.uuid4()))
    room: str = websocket.query_params.get("room", "general")

    await ws_manager.connect(websocket, client_id=client_id, room=room)
    logger.info("WS connected  client_id=%s  room=%s", client_id, room)

    try:
        await websocket.send_json({
            "type": "welcome",
            "client_id": client_id,
            "room": room,
            "message": "Connected to Layla WebSocket.",
        })

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Malformed JSON payload.",
                })
                continue

            await ws_manager.handle_client_message(
                websocket, client_id=client_id, room=room, data=data,
            )

    except WebSocketDisconnect:
        logger.info("WS disconnected  client_id=%s  room=%s", client_id, room)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS error  client_id=%s: %s", client_id, exc)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Internal error: {exc}",
            })
        except Exception:  # noqa: BLE001
            pass  # connection may already be closed
    finally:
        await ws_manager.disconnect(client_id)


@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(websocket: WebSocket, session_id: str):
    """Session-specific streaming endpoint.

    Subscribes the client to real-time updates for a particular agent
    session.  The *room* is set to the ``session_id`` so that broadcasts
    targeting the session reach only the relevant subscribers.

    Query params:
        client_id — optional identifier for the client (defaults to a UUID).
    """
    client_id: str = websocket.query_params.get("client_id", str(uuid.uuid4()))
    room: str = session_id

    await ws_manager.connect(websocket, client_id=client_id, room=room)
    logger.info(
        "WS stream connected  client_id=%s  session_id=%s", client_id, session_id,
    )

    try:
        await websocket.send_json({
            "type": "welcome",
            "client_id": client_id,
            "session_id": session_id,
            "message": f"Streaming session {session_id}.",
        })

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Malformed JSON payload.",
                })
                continue

            await ws_manager.handle_client_message(
                websocket, client_id=client_id, room=room, data=data,
            )

    except WebSocketDisconnect:
        logger.info(
            "WS stream disconnected  client_id=%s  session_id=%s",
            client_id, session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "WS stream error  client_id=%s  session_id=%s: %s",
            client_id, session_id, exc,
        )
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Internal error: {exc}",
            })
        except Exception:  # noqa: BLE001
            pass
    finally:
        await ws_manager.disconnect(client_id)


@router.get("/ws/clients")
async def list_connected_clients():
    """Return the list of currently connected WebSocket clients.

    Response shape::

        {"ok": true, "clients": [...], "count": N}
    """
    clients = ws_manager.list_clients()
    return {"ok": True, "clients": clients, "count": len(clients)}
