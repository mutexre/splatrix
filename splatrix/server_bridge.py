"""QThread bridge between the async WebSocket client and the Qt event loop.

Runs ``SplatrixClient`` in a dedicated thread with its own asyncio loop,
and emits Qt signals that the QML Backend can connect to.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from .client import SplatrixClient
from .protocol import (
    Operation,
    RunStageMsg,
    CancelMsg,
    GetStatusMsg,
    GetLogMsg,
    AcknowledgeMsg,
    RejectMsg,
)

logger = logging.getLogger("splatrix.server_bridge")


def _load_client_config() -> dict:
    config_path = Path.home() / ".splatrix" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except Exception:
            pass
    return {}


def _ensure_client_id() -> str:
    config_path = Path.home() / ".splatrix" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = _load_client_config()
    if "client_id" not in config:
        try:
            import coolname
            config["client_id"] = coolname.generate_slug(3)
        except ImportError:
            import uuid
            config["client_id"] = str(uuid.uuid4())[:12]
        config_path.write_text(json.dumps(config, indent=2))
    return config["client_id"]


class ServerBridge(QThread):
    """Bridges the async SplatrixClient into the Qt world.

    All public methods that talk to the server are thread-safe: they
    schedule coroutines on the internal asyncio loop and return immediately.
    Results arrive as Qt signals.
    """

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)
    accepted = pyqtSignal(str)                  # request_id
    progress = pyqtSignal(str, str, float)       # request_id, stage, progress
    completed = pyqtSignal(str, str)             # request_id, output_dir
    failed = pyqtSignal(str, str)                # request_id, error
    cancelled = pyqtSignal(str)                  # request_id
    acknowledged = pyqtSignal(str)               # request_id
    rejected = pyqtSignal(str)                   # request_id
    status_received = pyqtSignal(list)           # list of request dicts
    log_received = pyqtSignal(str, str)          # request_id, content

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client_id = _ensure_client_id()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[SplatrixClient] = None
        self._stopping = False

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def run(self):
        """Thread entry — creates an event loop and connects to the server."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        config = _load_client_config()
        servers = config.get("servers", {})
        default = config.get("default_server", "local")
        srv = servers.get(default, {})

        socket_path = None
        tcp_url = None
        if srv.get("type") == "unix":
            socket_path = Path(srv.get("socket", "~/.splatrix/server.sock")).expanduser()
        elif srv.get("type") == "tcp":
            host = srv.get("host", "localhost")
            port = srv.get("port", 8765)
            tcp_url = f"http://{host}:{port}/ws"
        else:
            socket_path = Path.home() / ".splatrix" / "server.sock"

        self._client = SplatrixClient(
            client_id=self._client_id,
            socket_path=socket_path,
            tcp_url=tcp_url,
            auto_reconnect=True,
        )

        self._register_handlers()

        try:
            self._loop.run_until_complete(self._connect_and_run())
        except Exception as exc:
            logger.exception("Server bridge loop crashed")
            self.connection_error.emit(str(exc))
        finally:
            self._loop.close()

    async def _connect_and_run(self):
        try:
            await self._client.connect()
            self.connected.emit()
        except ConnectionError as exc:
            self.connection_error.emit(str(exc))
            return

        while not self._stopping:
            await asyncio.sleep(0.5)

        await self._client.disconnect()

    def _register_handlers(self):
        c = self._client
        c.on("accepted", lambda d: self.accepted.emit(d.get("request_id", "")))
        c.on("progress", lambda d: self.progress.emit(
            d.get("request_id", ""),
            d.get("stage", ""),
            d.get("progress", 0.0),
        ))
        c.on("completed", lambda d: self.completed.emit(
            d.get("request_id", ""),
            d.get("output_dir", ""),
        ))
        c.on("failed", lambda d: self.failed.emit(
            d.get("request_id", ""),
            d.get("error", "unknown"),
        ))
        c.on("cancelled", lambda d: self.cancelled.emit(d.get("request_id", "")))
        c.on("acknowledged", lambda d: self.acknowledged.emit(d.get("request_id", "")))
        c.on("rejected", lambda d: self.rejected.emit(d.get("request_id", "")))
        c.on("status", lambda d: self.status_received.emit(d.get("active_requests", [])))
        c.on("log", lambda d: self.log_received.emit(
            d.get("request_id", ""),
            d.get("content", ""),
        ))

    def stop(self):
        self._stopping = True
        self.wait(5000)

    # ── Thread-safe request methods ───────────────────────────────────────────

    def _schedule(self, coro):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def request_run_stage(
        self,
        project_id: str,
        stage: str,
        input_dir: str,
        output_dir: str,
        depends_on: dict[str, int] | None = None,
        params: dict | None = None,
    ):
        async def _do():
            try:
                await self._client.run_stage(
                    project_id, stage, input_dir, output_dir,
                    depends_on or {}, params or {},
                )
            except Exception as exc:
                self.connection_error.emit(str(exc))
        self._schedule(_do())

    def request_cancel(self, request_id: str):
        async def _do():
            try:
                await self._client.cancel(request_id)
            except Exception as exc:
                logger.warning("Cancel failed: %s", exc)
        self._schedule(_do())

    def request_acknowledge(self, request_id: str):
        async def _do():
            try:
                await self._client.acknowledge(request_id)
            except Exception as exc:
                logger.warning("Acknowledge failed: %s", exc)
        self._schedule(_do())

    def request_reject(self, request_id: str):
        async def _do():
            try:
                await self._client.reject(request_id)
            except Exception as exc:
                logger.warning("Reject failed: %s", exc)
        self._schedule(_do())

    def request_status(self, project_id: str):
        async def _do():
            try:
                await self._client.get_status(project_id)
            except Exception as exc:
                logger.warning("Status request failed: %s", exc)
        self._schedule(_do())

    def request_log(self, request_id: str):
        async def _do():
            try:
                await self._client.get_log(request_id)
            except Exception as exc:
                logger.warning("Log request failed: %s", exc)
        self._schedule(_do())
