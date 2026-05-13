"""Tests for WebSocket connection manager."""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


class TestConnectionManager:
    def test_initial_state(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        assert mgr.client_count == 0
        assert mgr.get_connected_clients() == []

    @pytest.mark.asyncio
    async def test_connect(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "client-1")
        assert mgr.is_connected("client-1")
        assert mgr.client_count == 1

    @pytest.mark.asyncio
    async def test_disconnect(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "client-1")
        mgr.disconnect("client-1")
        assert not mgr.is_connected("client-1")
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        mgr.disconnect("ghost")  # Should not raise

    @pytest.mark.asyncio
    async def test_send_personal(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "client-1")
        await mgr.send_personal({"type": "test"}, "client-1")
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "client-1", room="room-a")
        await mgr.connect(ws2, "client-2", room="room-a")
        await mgr.broadcast({"type": "test"}, room="room-a")
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_exclude(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "client-1", room="room-a")
        await mgr.connect(ws2, "client-2", room="room-a")
        await mgr.broadcast({"type": "test"}, room="room-a", exclude="client-1")
        ws1.send_json.assert_not_called()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_all(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "c1", room="room-a")
        await mgr.connect(ws2, "c2", room="room-b")
        await mgr.broadcast_all({"type": "system"})
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connected_clients(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "client-1", room="lobby")
        clients = mgr.get_connected_clients()
        assert len(clients) == 1
        assert clients[0]["client_id"] == "client-1"
        assert clients[0]["room"] == "lobby"
        assert "connected_at" in clients[0]

    @pytest.mark.asyncio
    async def test_get_room_members(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "c1", room="room-x")
        await mgr.connect(ws2, "c2", room="room-x")
        members = mgr.get_room_members("room-x")
        assert "c1" in members
        assert "c2" in members

    @pytest.mark.asyncio
    async def test_empty_room_members(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        members = mgr.get_room_members("empty-room")
        assert members == []

    @pytest.mark.asyncio
    async def test_multiple_rooms(self):
        from services.ws_manager import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "c1", room="room-a")
        await mgr.connect(ws2, "c2", room="room-b")
        assert len(mgr.get_room_members("room-a")) == 1
        assert len(mgr.get_room_members("room-b")) == 1


class TestCreateMessage:
    def test_structure(self):
        from services.ws_manager import create_message, MSG_SYSTEM
        msg = create_message(MSG_SYSTEM, {"text": "hello"})
        assert msg["type"] == "system"
        assert msg["data"]["text"] == "hello"
        assert msg["sender"] == "layla"
        assert "timestamp" in msg

    def test_custom_sender(self):
        from services.ws_manager import create_message, MSG_RESPONSE
        msg = create_message(MSG_RESPONSE, {}, sender="user")
        assert msg["sender"] == "user"


class TestHandleClientMessage:
    @pytest.mark.asyncio
    async def test_heartbeat(self):
        from services.ws_manager import handle_client_message
        result = await handle_client_message({"type": "heartbeat"}, "c1")
        assert result is not None
        assert result["type"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_unknown_type(self):
        from services.ws_manager import handle_client_message
        result = await handle_client_message({"type": "unknown_xyz"}, "c1")
        # Should handle gracefully (return None or error)
        assert result is None or isinstance(result, dict)


class TestModuleSingleton:
    def test_manager_exists(self):
        from services.ws_manager import manager
        assert manager is not None
        assert hasattr(manager, "connect")
        assert hasattr(manager, "broadcast")
