"""Async WebSocket client for communicating with the Splatrix server.

Used by both the PyQt UI (via a QThread bridge) and the CLI.

Supports:
  - Automatic reconnection with exponential backoff
  - Heartbeat via aiohttp's built-in ping/pong
  - Event handler registration by message type
  - Sending typed message dataclasses
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

import aiohttp

from .protocol import (
    PROTOCOL_VERSION,
    HelloMsg,
    from_json,
    parse_server_event,
    to_json,
)

logger = logging.getLogger("splatrix.client")

EventHandler = Callable[[dict[str, Any]], Any]

DEFAULT_SOCKET = Path.home() / ".splatrix" / "server.sock"

# Reconnection constants
_INITIAL_BACKOFF = 0.5
_MAX_BACKOFF = 30.0
_BACKOFF_FACTOR = 2.0


class ServerError(Exception):
    """Raised when the server returns an error event."""
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


class SplatrixClient:
    """Async WebSocket client with reconnection and event dispatch."""

    def __init__(
        self,
        client_id: str,
        socket_path: Optional[str | Path] = None,
        tcp_url: Optional[str] = None,
        auto_reconnect: bool = True,
    ):
        self.client_id = client_id
        self._socket_path = str(socket_path) if socket_path else str(DEFAULT_SOCKET)
        self._tcp_url = tcp_url
        self._auto_reconnect = auto_reconnect

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._connected = asyncio.Event()
        self._closing = False
        self._recv_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the server, perform handshake.

        Raises ``ConnectionError`` if the server is unreachable.
        """
        self._closing = False
        await self._do_connect()
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _do_connect(self) -> None:
        if self._session is None:
            connector = aiohttp.UnixConnector(path=self._socket_path) if not self._tcp_url else None
            self._session = aiohttp.ClientSession(connector=connector)

        url = self._tcp_url or "http://localhost/ws"
        try:
            self._ws = await self._session.ws_connect(url, heartbeat=30)
        except (aiohttp.ClientError, OSError) as exc:
            raise ConnectionError(f"Cannot connect to server: {exc}") from exc

        hello = HelloMsg(protocol_version=PROTOCOL_VERSION, client_id=self.client_id)
        await self._ws.send_str(to_json(hello))

        resp = await self._ws.receive()
        if resp.type != aiohttp.WSMsgType.TEXT:
            raise ConnectionError("Server did not respond to hello")

        data = from_json(resp.data)
        if data.get("type") == "error":
            raise ServerError(data.get("code", ""), data.get("message", ""))
        if data.get("type") != "hello":
            raise ConnectionError(f"Unexpected server response: {data}")

        self._connected.set()
        logger.info("Connected to server (protocol v%s)", data.get("protocol_version"))

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._closing = True
        self._connected.clear()
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
            self._session = None

    # ── Sending ───────────────────────────────────────────────────────────────

    async def send(self, msg) -> None:
        """Send a message dataclass to the server."""
        if not self.is_connected:
            raise ConnectionError("Not connected to server")
        await self._ws.send_str(to_json(msg))

    async def send_and_wait(self, msg, wait_for_type: str, timeout: float = 30.0) -> dict:
        """Send a message and wait for a specific response type.

        Returns the response dict.  Raises ``TimeoutError`` or ``ServerError``.
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        key = f"{wait_for_type}:{id(future)}"

        def _handler(data: dict):
            if not future.done():
                future.set_result(data)

        self.on(wait_for_type, _handler)
        self.on("error", lambda d: future.set_exception(ServerError(d.get("code", ""), d.get("message", "")))
                if not future.done() else None)

        try:
            await self.send(msg)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.off(wait_for_type, _handler)

    # ── Event handlers ────────────────────────────────────────────────────────

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a server event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: EventHandler) -> None:
        """Unregister a handler."""
        handlers = self._handlers.get(event_type, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def _dispatch(self, data: dict) -> None:
        event_type = data.get("type", "")
        for handler in self._handlers.get(event_type, []):
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("Handler error for event %s", event_type)

    # ── Receive loop ──────────────────────────────────────────────────────────

    async def _recv_loop(self) -> None:
        backoff = _INITIAL_BACKOFF
        while not self._closing:
            try:
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = from_json(msg.data)
                        except ValueError:
                            logger.warning("Received malformed JSON from server")
                            continue
                        self._dispatch(data)
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                        break

                self._connected.clear()
                if self._closing:
                    return

                if not self._auto_reconnect:
                    logger.info("Disconnected from server (no auto-reconnect)")
                    return

                logger.warning("Connection lost, reconnecting in %.1fs...", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)

                try:
                    await self._do_connect()
                    backoff = _INITIAL_BACKOFF
                    logger.info("Reconnected to server")
                except (ConnectionError, ServerError):
                    continue

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Unexpected error in receive loop")
                if self._closing:
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)

    # ── Convenience methods ───────────────────────────────────────────────────

    async def run_stage(
        self,
        project_id: str,
        stage: str,
        input_dir: str,
        output_dir: str,
        depends_on: dict[str, int] | None = None,
        params: dict | None = None,
    ) -> str:
        """Send a ``run_stage`` request and return the ``request_id``."""
        from .protocol import RunStageMsg
        msg = RunStageMsg(
            client_id=self.client_id,
            project_id=project_id,
            stage=stage,
            input_dir=input_dir,
            output_dir=output_dir,
            depends_on=depends_on or {},
            params=params or {},
        )
        resp = await self.send_and_wait(msg, "accepted")
        return resp["request_id"]

    async def cancel(self, request_id: str) -> None:
        from .protocol import CancelMsg
        await self.send_and_wait(CancelMsg(request_id=request_id), "cancelled")

    async def acknowledge(self, request_id: str) -> None:
        from .protocol import AcknowledgeMsg
        await self.send_and_wait(AcknowledgeMsg(request_id=request_id), "acknowledged")

    async def reject(self, request_id: str) -> None:
        from .protocol import RejectMsg
        await self.send_and_wait(RejectMsg(request_id=request_id), "rejected")

    async def get_status(self, project_id: str) -> list[dict]:
        from .protocol import GetStatusMsg
        msg = GetStatusMsg(client_id=self.client_id, project_id=project_id)
        resp = await self.send_and_wait(msg, "status")
        return resp.get("active_requests", [])

    async def get_log(self, request_id: str) -> str:
        from .protocol import GetLogMsg
        resp = await self.send_and_wait(GetLogMsg(request_id=request_id), "log")
        return resp.get("content", "")
