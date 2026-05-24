"""Conformance tests: WebSocket route registration."""
from __future__ import annotations

import pytest
from fastapi import WebSocket
from starlette.testclient import TestClient


def test_websocket_route_registers_and_handles_connection(adapter):
    # Litestar requires the WebSocket parameter to be named `socket`.
    # FastAPI accepts any name. Use `socket` for cross-engine compatibility.
    async def ws_endpoint(socket: WebSocket) -> None:
        await socket.accept()
        data = await socket.receive_text()
        await socket.send_text(f"echo:{data}")
        await socket.close()

    adapter.add_websocket_route("/ws", ws_endpoint)

    client = TestClient(adapter.get_http_server())
    with client.websocket_connect("/ws") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "echo:hello"
