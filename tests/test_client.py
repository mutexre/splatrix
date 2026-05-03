"""Tests for splatrix.client — WebSocket client handshake, events, reconnection."""

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web, WSMsgType

from splatrix.client import SplatrixClient, ServerError
from splatrix.protocol import PROTOCOL_VERSION, to_json, HelloEvent, ErrorEvent


def _short_sock_path() -> Path:
    """Return a short socket path under /tmp (macOS limits AF_UNIX to 104 chars)."""
    return Path(tempfile.gettempdir()) / f"splatrix_test_{uuid.uuid4().hex[:8]}.sock"


@pytest_asyncio.fixture
async def echo_server(tmp_path):
    """Minimal WebSocket server that responds to hello and echoes messages."""
    sock_path = _short_sock_path()
    received = []

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                received.append(data)

                if data.get("type") == "hello":
                    resp = HelloEvent(
                        protocol_version=PROTOCOL_VERSION,
                        server_id="test-server",
                    )
                    await ws.send_str(to_json(resp))
                elif data.get("type") == "run_stage":
                    await ws.send_str(json.dumps({
                        "type": "accepted",
                        "request_id": "test-req-123",
                    }))
                elif data.get("type") == "get_status":
                    await ws.send_str(json.dumps({
                        "type": "status",
                        "active_requests": [],
                    }))
                elif data.get("type") == "cancel":
                    await ws.send_str(json.dumps({
                        "type": "cancelled",
                        "request_id": data.get("request_id", ""),
                    }))
                elif data.get("type") == "acknowledge":
                    await ws.send_str(json.dumps({
                        "type": "acknowledged",
                        "request_id": data.get("request_id", ""),
                    }))
                elif data.get("type") == "reject":
                    await ws.send_str(json.dumps({
                        "type": "rejected",
                        "request_id": data.get("request_id", ""),
                    }))
                elif data.get("type") == "get_log":
                    await ws.send_str(json.dumps({
                        "type": "log",
                        "request_id": data.get("request_id", ""),
                        "content": "test log output",
                    }))

        return ws

    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.UnixSite(runner, str(sock_path))
    await site.start()

    yield {"sock_path": sock_path, "received": received}

    await runner.cleanup()
    sock_path.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client(echo_server):
    c = SplatrixClient(
        client_id="test-client",
        socket_path=echo_server["sock_path"],
        auto_reconnect=False,
    )
    await c.connect()
    yield c
    await c.disconnect()


class TestClientHandshake:
    @pytest.mark.asyncio
    async def test_connects_successfully(self, client):
        assert client.is_connected

    @pytest.mark.asyncio
    async def test_wrong_protocol_version(self):
        sock_path = _short_sock_path()

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await ws.send_str(to_json(ErrorEvent(
                        code="unsupported_protocol",
                        message="bad version",
                    )))
                    await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/ws", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.UnixSite(runner, str(sock_path))
        await site.start()

        c = SplatrixClient(
            client_id="test", socket_path=sock_path, auto_reconnect=False
        )
        with pytest.raises(ServerError, match="unsupported_protocol"):
            await c.connect()

        await runner.cleanup()
        sock_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_server_unreachable(self):
        c = SplatrixClient(
            client_id="test",
            socket_path=_short_sock_path(),
            auto_reconnect=False,
        )
        with pytest.raises(ConnectionError):
            await c.connect()


class TestClientOperations:
    @pytest.mark.asyncio
    async def test_run_stage(self, client):
        rid = await client.run_stage(
            project_id="proj-1",
            stage="frames",
            input_dir="/tmp/in",
            output_dir="/tmp/out",
        )
        assert rid == "test-req-123"

    @pytest.mark.asyncio
    async def test_get_status(self, client):
        requests = await client.get_status("proj-1")
        assert isinstance(requests, list)

    @pytest.mark.asyncio
    async def test_cancel(self, client):
        await client.cancel("test-req-123")

    @pytest.mark.asyncio
    async def test_acknowledge(self, client):
        await client.acknowledge("test-req-123")

    @pytest.mark.asyncio
    async def test_reject(self, client):
        await client.reject("test-req-123")

    @pytest.mark.asyncio
    async def test_get_log(self, client):
        log = await client.get_log("test-req-123")
        assert "test log output" in log


class TestEventDispatch:
    @pytest.mark.asyncio
    async def test_on_progress(self, client):
        events = []
        client.on("progress", lambda d: events.append(d))

        # Manually inject a progress event
        client._dispatch({"type": "progress", "request_id": "r1", "stage": "frames", "progress": 0.5})
        assert len(events) == 1
        assert events[0]["progress"] == 0.5

    @pytest.mark.asyncio
    async def test_unregistered_event_ignored(self, client):
        client._dispatch({"type": "unknown_event", "data": 123})
