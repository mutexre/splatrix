"""Splatrix processing server.

An aiohttp WebSocket server that executes pipeline stages on behalf of
clients.  Entirely stateless between restarts except for a small SQLite
database tracking active/completed requests and their workspace paths.

Usage::

    python -m splatrix.server [--socket PATH] [--tcp HOST:PORT]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import signal
import sqlite3
import time
import uuid as _uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from aiohttp import web, WSMsgType

from .protocol import (
    PROTOCOL_VERSION,
    AcceptedEvent,
    AcknowledgedEvent,
    CancelledEvent,
    CompletedEvent,
    ErrorEvent,
    FailedEvent,
    HelloEvent,
    LogEvent,
    Operation,
    ProgressEvent,
    RejectedEvent,
    RequestStatus,
    StatusEvent,
    from_json,
    parse_client_msg,
    to_json,
)

logger = logging.getLogger("splatrix.server")

DEFAULT_SOCKET = Path.home() / ".splatrix" / "server.sock"
TIMEOUT_HOURS = 1
CLEANUP_INTERVAL_SECONDS = 600  # 10 min
PROGRESS_THROTTLE_SECONDS = 0.25  # max 4 events/sec

# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id   TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL,
    project_id   TEXT NOT NULL,
    operation    TEXT NOT NULL,
    status       TEXT NOT NULL,
    depends_on   TEXT,
    input_dir    TEXT,
    output_dir   TEXT,
    params       TEXT,
    log_text     TEXT DEFAULT '',
    started_at   TEXT,
    completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active
    ON requests(client_id, project_id) WHERE status = 'running';
"""


class RequestDB:
    """Thin wrapper around a synchronous SQLite connection."""

    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def insert_request(self, **kw) -> None:
        cols = ", ".join(kw)
        placeholders = ", ".join(f":{k}" for k in kw)
        self._conn.execute(f"INSERT INTO requests ({cols}) VALUES ({placeholders})", kw)
        self._conn.commit()

    def update_status(self, request_id: str, status: str, **extra) -> None:
        sets = ["status = :status"]
        params: dict[str, Any] = {"request_id": request_id, "status": status}
        for k, v in extra.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        self._conn.execute(
            f"UPDATE requests SET {', '.join(sets)} WHERE request_id = :request_id",
            params,
        )
        self._conn.commit()

    def append_log(self, request_id: str, text: str) -> None:
        self._conn.execute(
            "UPDATE requests SET log_text = log_text || :text WHERE request_id = :rid",
            {"text": text, "rid": request_id},
        )
        self._conn.commit()

    def get(self, request_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_active(self, client_id: str, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM requests WHERE client_id = ? AND project_id = ? "
            "AND status IN ('running', 'completed', 'failed', 'crashed')",
            (client_id, project_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def has_running(self, client_id: str, project_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM requests WHERE client_id = ? AND project_id = ? AND status = 'running'",
            (client_id, project_id),
        ).fetchone()
        return row is not None

    def delete(self, request_id: str) -> None:
        self._conn.execute("DELETE FROM requests WHERE request_id = ?", (request_id,))
        self._conn.commit()

    def get_all_active_dirs(self) -> list[str]:
        """Return all input_dir and output_dir for non-terminal requests."""
        rows = self._conn.execute(
            "SELECT input_dir, output_dir FROM requests WHERE status IN ('running', 'completed')"
        ).fetchall()
        dirs: list[str] = []
        for r in rows:
            if r["input_dir"]:
                dirs.append(r["input_dir"])
            if r["output_dir"]:
                dirs.append(r["output_dir"])
        return dirs

    # -- Crash recovery & cleanup ------------------------------------------

    def mark_crashed(self) -> list[dict]:
        """Mark all running requests as crashed.  Returns them."""
        rows = self._conn.execute(
            "SELECT * FROM requests WHERE status = 'running'"
        ).fetchall()
        crashed = [dict(r) for r in rows]
        if crashed:
            self._conn.execute(
                "UPDATE requests SET status = 'crashed', completed_at = ? WHERE status = 'running'",
                (datetime.now(timezone.utc).isoformat(),),
            )
            self._conn.commit()
        return crashed

    def cleanup_stale(self, max_age: timedelta) -> list[dict]:
        """Delete requests older than *max_age* that are in a terminal state.
        Returns the deleted rows (caller should delete workspace dirs)."""
        cutoff = (datetime.now(timezone.utc) - max_age).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM requests WHERE status IN ('completed', 'failed', 'cancelled', 'crashed') "
            "AND completed_at < ?",
            (cutoff,),
        ).fetchall()
        stale = [dict(r) for r in rows]
        if stale:
            ids = [r["request_id"] for r in stale]
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(f"DELETE FROM requests WHERE request_id IN ({placeholders})", ids)
            self._conn.commit()
        return stale


# ---------------------------------------------------------------------------
# Stage executor (runs in a worker process)
# ---------------------------------------------------------------------------

def _execute_stage(
    stage: str,
    input_dir: str,
    output_dir: str,
    params: dict,
    progress_file: str,
) -> dict:
    """Execute a pipeline stage synchronously.

    Runs in a separate process via ``ProcessPoolExecutor``.
    Writes progress updates to *progress_file* as JSON lines.
    """
    import json as _json
    from .protocol import Stage as _Stage

    _stage = _Stage(stage)
    pf = open(progress_file, "a")

    def _report(stage_key: str, progress: float):
        pf.write(_json.dumps({"stage": stage_key, "progress": progress}) + "\n")
        pf.flush()

    _HANDLERS = {
        _Stage.FRAMES: _run_frames,
        _Stage.FEATURE_EXTRACT: _run_feature_extract,
        _Stage.FEATURE_MATCH: _run_feature_match,
        _Stage.RECONSTRUCTION: _run_reconstruction,
        _Stage.TRAINING: _run_training,
        _Stage.EXPORT: _run_export,
    }

    handler = _HANDLERS.get(_stage)
    if handler is None:
        raise ValueError(f"Unknown stage: {stage}")

    try:
        return handler(input_dir, output_dir, params, _report)
    except SystemExit as e:
        raise RuntimeError(f"Stage aborted with exit code {e.code}") from e
    finally:
        pf.close()


# ---------------------------------------------------------------------------
# Individual stage handlers
# ---------------------------------------------------------------------------

def _colmap_gpu_flags() -> tuple[str, str, str]:
    """Detect COLMAP binary and return (colmap_cmd, extract_gpu_flag, match_gpu_flag)."""
    import subprocess as _sp
    colmap_cmd = shutil.which("colmap") or "colmap"
    try:
        _h = _sp.run(
            [colmap_cmd, "feature_extractor", "-h"],
            capture_output=True, text=True, timeout=10,
        )
        _ht = (_h.stdout or "") + (_h.stderr or "")
    except Exception:
        _ht = ""
    if "FeatureExtraction" in _ht:
        return colmap_cmd, "--FeatureExtraction.use_gpu 1", "--FeatureMatching.use_gpu 1"
    return colmap_cmd, "--SiftExtraction.use_gpu 1", "--SiftMatching.use_gpu 1"


def _run_frames(input_dir: str, output_dir: str, params: dict, report) -> dict:
    from .protocol import Stage
    report(Stage.FRAMES.value, 0.0)

    video_files = list(Path(input_dir).glob("*"))
    if not video_files:
        raise FileNotFoundError(f"No input files in {input_dir}")
    video_path = Path(video_files[0])
    out = Path(output_dir)
    image_dir = out / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    num_frames = params.get("num_frames_target", 300)

    from nerfstudio.process_data import process_data_utils
    _summary, num_extracted = process_data_utils.convert_video_to_images(
        video_path=video_path,
        image_dir=image_dir,
        num_frames_target=num_frames,
        num_downscales=3,
        crop_factor=(0.0, 0.0, 0.0, 0.0),
        verbose=True,
    )
    report(Stage.FRAMES.value, 1.0)
    return {"images_dir": str(image_dir), "frame_count": num_extracted}


def _run_feature_extract(input_dir: str, output_dir: str, params: dict, report) -> dict:
    from .protocol import Stage
    from nerfstudio.process_data.colmap_utils import run_command
    report(Stage.FEATURE_EXTRACT.value, 0.0)

    inp = Path(input_dir)
    out = Path(output_dir)
    image_dir = _find_subdir(inp, "images")
    shutil.copytree(str(image_dir), str(out / "images"))

    colmap_dir = out / "colmap"
    colmap_dir.mkdir(parents=True, exist_ok=True)
    db_path = colmap_dir / "database.db"

    colmap_cmd, gpu_extract, _ = _colmap_gpu_flags()
    extract_cmd = " ".join([
        f"{colmap_cmd} feature_extractor",
        f"--database_path {db_path}",
        f"--image_path {out / 'images'}",
        "--ImageReader.single_camera 1",
        "--ImageReader.camera_model OPENCV",
        gpu_extract,
    ])
    run_command(extract_cmd, verbose=True)
    report(Stage.FEATURE_EXTRACT.value, 1.0)
    return {"colmap_dir": str(colmap_dir)}


def _run_feature_match(input_dir: str, output_dir: str, params: dict, report) -> dict:
    from .protocol import Stage
    from nerfstudio.process_data.colmap_utils import run_command
    report(Stage.FEATURE_MATCH.value, 0.0)

    inp = Path(input_dir)
    out = Path(output_dir)
    shutil.copytree(str(_find_subdir(inp, "images")), str(out / "images"))
    shutil.copytree(str(_find_subdir(inp, "colmap")), str(out / "colmap"))

    db_path = out / "colmap" / "database.db"
    colmap_cmd, _, gpu_match = _colmap_gpu_flags()
    matching_method = "sequential"
    match_cmd = " ".join([
        f"{colmap_cmd} {matching_method}_matcher",
        f"--database_path {db_path}",
        gpu_match,
    ])
    run_command(match_cmd, verbose=True)
    report(Stage.FEATURE_MATCH.value, 1.0)
    return {"colmap_dir": str(out / "colmap")}


def _run_reconstruction(input_dir: str, output_dir: str, params: dict, report) -> dict:
    from .protocol import Stage
    from nerfstudio.process_data.colmap_utils import get_colmap_version, run_command, colmap_to_json
    from packaging.version import Version
    report(Stage.RECONSTRUCTION.value, 0.0)

    inp = Path(input_dir)
    out = Path(output_dir)
    shutil.copytree(str(_find_subdir(inp, "images")), str(out / "images"))
    shutil.copytree(str(_find_subdir(inp, "colmap")), str(out / "colmap"))

    db_path = out / "colmap" / "database.db"
    image_dir = out / "images"
    sparse_dir = out / "colmap" / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    colmap_cmd = shutil.which("colmap") or "colmap"
    colmap_version = get_colmap_version(colmap_cmd)
    mapper_parts = [
        f"{colmap_cmd} mapper",
        f"--database_path {db_path}",
        f"--image_path {image_dir}",
        f"--output_path {sparse_dir}",
    ]
    if colmap_version >= Version("3.7"):
        mapper_parts.append("--Mapper.ba_global_function_tolerance=1e-6")
    run_command(" ".join(mapper_parts), verbose=True)
    report(Stage.RECONSTRUCTION.value, 0.5)

    bundle_cmd = " ".join([
        f"{colmap_cmd} bundle_adjuster",
        f"--input_path {sparse_dir}/0",
        f"--output_path {sparse_dir}/0",
        "--BundleAdjustment.refine_principal_point 1",
    ])
    run_command(bundle_cmd, verbose=True)
    report(Stage.RECONSTRUCTION.value, 0.8)

    model_path = out / "colmap" / "sparse" / "0"
    if (model_path / "cameras.bin").exists():
        colmap_to_json(recon_dir=model_path, output_dir=out)
    else:
        raise RuntimeError(f"COLMAP reconstruction failed — no cameras.bin in {model_path}")

    report(Stage.RECONSTRUCTION.value, 1.0)
    return {"data_dir": str(out), "transforms_path": str(out / "transforms.json")}


def _find_subdir(root: Path, name: str) -> Path:
    """Locate a subdirectory named *name* in *root* or one level below."""
    if (root / name).is_dir():
        return root / name
    for child in root.iterdir():
        if child.is_dir() and (child / name).is_dir():
            return child / name
    raise FileNotFoundError(f"Cannot find '{name}' directory in {root}")


def _find_data_dir(input_dir: str) -> str:
    """Find the actual nerfstudio/COLMAP data directory inside a workspace input.

    The client clones project data into the workspace input folder, which means
    the actual data is typically one level down (e.g. ``input_dir/nerfstudio_data/``).
    This function searches for ``transforms.json`` or ``cameras.bin`` to locate it.
    """
    root = Path(input_dir)
    if (root / "transforms.json").exists() or (root / "sparse" / "0" / "cameras.bin").exists():
        return input_dir
    for child in root.iterdir():
        if child.is_dir():
            if (child / "transforms.json").exists() or (child / "sparse" / "0" / "cameras.bin").exists():
                return str(child)
    raise FileNotFoundError(
        f"No nerfstudio dataset (transforms.json) or COLMAP data (cameras.bin) found in {input_dir}"
    )


def _run_training(input_dir: str, output_dir: str, params: dict, report) -> dict:
    from .training_backend import TrainingBackend
    from .protocol import Stage

    data_dir = _find_data_dir(input_dir)
    backend = TrainingBackend.auto_select()
    max_iter = params.get("max_iterations", 30000)

    def progress_cb(msg: str, progress: float):
        report(Stage.TRAINING.value, progress)

    result = backend.train(
        data_dir=data_dir,
        output_dir=output_dir,
        max_iterations=max_iter,
        progress_callback=progress_cb,
    )
    return {
        "output_dir": result.output_dir,
        "config_path": result.config_path,
        "checkpoint_dir": result.checkpoint_dir,
    }


def _run_export(input_dir: str, output_dir: str, params: dict, report) -> dict:
    import shutil as _shutil
    from .training_backend import TrainingBackend, TrainingResult
    from .protocol import Stage

    report(Stage.EXPORT.value, 0.0)
    root = Path(input_dir)
    output_ply = Path(output_dir) / "output.ply"

    existing_ply = list(root.rglob("point_cloud.ply"))
    if existing_ply:
        report(Stage.EXPORT.value, 0.5)
        _shutil.copy2(str(existing_ply[0]), str(output_ply))
        report(Stage.EXPORT.value, 1.0)
        return {"ply_path": str(output_ply)}

    checkpoints = sorted(root.rglob("step-*.ckpt"))
    if not checkpoints:
        checkpoints = sorted(root.rglob("*.ckpt"))

    msplat_ckpts = sorted(root.rglob("*.msplat"))

    if not checkpoints and not msplat_ckpts:
        raise FileNotFoundError(
            f"No checkpoints or PLY found in {input_dir}. "
            f"Contents: {[p.name for p in root.rglob('*') if p.is_file()][:20]}"
        )

    backend = TrainingBackend.auto_select()

    def progress_cb(msg: str, progress: float):
        report(Stage.EXPORT.value, progress)

    if msplat_ckpts:
        latest = max(msplat_ckpts, key=lambda p: p.stat().st_mtime)
        result = TrainingResult(
            output_dir=str(latest.parent),
            checkpoint_path=str(latest),
            extra={"data_dir": str(latest.parent)},
        )
    else:
        latest = max(checkpoints, key=lambda p: p.stat().st_mtime)
        checkpoint_dir = latest.parent
        result = TrainingResult(
            output_dir=str(checkpoint_dir.parent),
            checkpoint_dir=str(checkpoint_dir),
        )

    ply_path = backend.export_ply(result, str(output_ply), progress_cb)
    return {"ply_path": str(ply_path)}


# ---------------------------------------------------------------------------
# Server application
# ---------------------------------------------------------------------------

class SplatrixServer:
    def __init__(self, db_path: Path, socket_path: Optional[Path] = None,
                 tcp_host: Optional[str] = None, tcp_port: Optional[int] = None,
                 use_thread_executor: bool = False):
        self.db = RequestDB(db_path)
        self.socket_path = socket_path
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.app = web.Application()
        self.app.router.add_get("/ws", self._ws_handler)
        self._clients: dict[int, web.WebSocketResponse] = {}
        self._request_ws: dict[str, int] = {}  # request_id -> ws id
        self._running_tasks: dict[str, asyncio.Task] = {}  # request_id -> task
        if use_thread_executor:
            self._executor = ThreadPoolExecutor(max_workers=2)
        else:
            self._executor = ProcessPoolExecutor(max_workers=2)
        self._shutdown_event = asyncio.Event()

    async def start(self):
        self._recover_crashed()
        runner = web.AppRunner(self.app)
        await runner.setup()

        if self.socket_path:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            if self.socket_path.exists():
                self.socket_path.unlink()
            site = web.UnixSite(runner, str(self.socket_path))
            await site.start()
            logger.info("Listening on unix:%s", self.socket_path)

        if self.tcp_host:
            site = web.TCPSite(runner, self.tcp_host, self.tcp_port or 8765)
            await site.start()
            logger.info("Listening on tcp:%s:%s", self.tcp_host, self.tcp_port or 8765)

        asyncio.create_task(self._cleanup_loop())
        logger.info("Server ready")
        await self._shutdown_event.wait()

    def _recover_crashed(self):
        crashed = self.db.mark_crashed()
        for req in crashed:
            logger.warning("Recovered crashed request %s (op=%s)", req["request_id"], req["operation"])
            _delete_dir(req.get("input_dir"))
            _delete_dir(req.get("output_dir"))

    async def _cleanup_loop(self):
        while not self._shutdown_event.is_set():
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            stale = self.db.cleanup_stale(timedelta(hours=TIMEOUT_HOURS))
            for req in stale:
                logger.info("Cleaned up stale request %s", req["request_id"])
                _delete_dir(req.get("input_dir"))
                _delete_dir(req.get("output_dir"))

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        ws_id = id(ws)
        self._clients[ws_id] = ws
        handshake_done = False
        client_id: Optional[str] = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = from_json(msg.data)
                    except ValueError:
                        await _send(ws, ErrorEvent(code="invalid_json", message="Malformed JSON"))
                        continue

                    msg_type = data.get("type")

                    if not handshake_done:
                        if msg_type != "hello":
                            await _send(ws, ErrorEvent(code="handshake_required", message="Send hello first"))
                            continue
                        pv = data.get("protocol_version", 0)
                        if pv != PROTOCOL_VERSION:
                            await _send(ws, ErrorEvent(
                                code="unsupported_protocol",
                                message=f"Server supports protocol {PROTOCOL_VERSION}, client sent {pv}",
                            ))
                            await ws.close()
                            break
                        client_id = data.get("client_id", "unknown")
                        await _send(ws, HelloEvent(protocol_version=PROTOCOL_VERSION, server_id="local"))
                        handshake_done = True
                        continue

                    await self._handle_msg(ws, ws_id, data, client_id)

                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.pop(ws_id, None)
            # Clean up request→ws mapping for this client
            dead = [rid for rid, wid in self._request_ws.items() if wid == ws_id]
            for rid in dead:
                del self._request_ws[rid]

        return ws

    async def _handle_msg(self, ws: web.WebSocketResponse, ws_id: int,
                          data: dict, client_id: str):
        msg_type = data.get("type")

        if msg_type == "run_stage":
            await self._handle_run_stage(ws, ws_id, data, client_id)
        elif msg_type == "cancel":
            await self._handle_cancel(ws, data)
        elif msg_type == "get_status":
            await self._handle_get_status(ws, data, client_id)
        elif msg_type == "get_log":
            await self._handle_get_log(ws, data)
        elif msg_type == "acknowledge":
            await self._handle_acknowledge(ws, data)
        elif msg_type == "reject":
            await self._handle_reject(ws, data)
        else:
            await _send(ws, ErrorEvent(code="unknown_type", message=f"Unknown message type: {msg_type}"))

    # ── Message handlers ──────────────────────────────────────────────────────

    async def _handle_run_stage(self, ws, ws_id, data, client_id):
        project_id = data.get("project_id", "")
        stage = data.get("stage") or data.get("operation", "")
        input_dir = data.get("input_dir", "")
        output_dir = data.get("output_dir", "")
        depends_on = data.get("depends_on", {})
        params = data.get("params", {})

        if not input_dir or not Path(input_dir).is_dir():
            await _send(ws, ErrorEvent(code="invalid_input", message=f"input_dir does not exist: {input_dir}"))
            return

        if self.db.has_running(client_id, project_id):
            await _send(ws, ErrorEvent(
                code="already_running",
                message=f"A request is already running for ({client_id}, {project_id})",
            ))
            return

        request_id = str(_uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self.db.insert_request(
            request_id=request_id,
            client_id=client_id,
            project_id=project_id,
            operation=stage,
            status=RequestStatus.RUNNING.value,
            depends_on=json.dumps(depends_on),
            input_dir=input_dir,
            output_dir=output_dir,
            params=json.dumps(params),
            started_at=now,
        )

        self._request_ws[request_id] = ws_id
        await _send(ws, AcceptedEvent(request_id=request_id))

        task = asyncio.create_task(self._run_stage(request_id, stage, input_dir, output_dir, params))
        self._running_tasks[request_id] = task

    async def _run_stage(self, request_id: str, stage: str,
                         input_dir: str, output_dir: str, params: dict):
        progress_file = Path(output_dir) / ".progress"
        loop = asyncio.get_event_loop()

        try:
            future = loop.run_in_executor(
                self._executor,
                _execute_stage,
                stage, input_dir, output_dir, params, str(progress_file),
            )

            progress_task = asyncio.create_task(
                self._stream_progress(request_id, progress_file)
            )

            result = await future
            progress_task.cancel()

            _delete_dir(input_dir)

            self.db.update_status(
                request_id, RequestStatus.COMPLETED.value,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

            await self._send_to_request(request_id, CompletedEvent(
                request_id=request_id,
                output_dir=output_dir,
            ))

        except asyncio.CancelledError:
            _delete_dir(input_dir)
            _delete_dir(output_dir)
            self.db.update_status(
                request_id, RequestStatus.CANCELLED.value,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._send_to_request(request_id, CancelledEvent(request_id=request_id))

        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.exception("Stage execution failed for %s", request_id)
            _delete_dir(input_dir)
            _delete_dir(output_dir)
            self.db.update_status(
                request_id, RequestStatus.FAILED.value,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            self.db.append_log(request_id, f"\n--- ERROR ---\n{exc}\n")
            await self._send_to_request(request_id, FailedEvent(
                request_id=request_id, error=str(exc),
            ))

        finally:
            self._running_tasks.pop(request_id, None)

    async def _stream_progress(self, request_id: str, progress_file: Path):
        """Tail the progress file and send throttled progress events."""
        last_send = 0.0
        pos = 0
        while True:
            await asyncio.sleep(0.1)
            if not progress_file.exists():
                continue
            try:
                with open(progress_file) as f:
                    f.seek(pos)
                    lines = f.readlines()
                    pos = f.tell()
            except OSError:
                continue

            now = time.monotonic()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if now - last_send >= PROGRESS_THROTTLE_SECONDS:
                    await self._send_to_request(request_id, ProgressEvent(
                        request_id=request_id,
                        stage=p.get("stage", ""),
                        progress=p.get("progress", 0.0),
                    ))
                    last_send = now

    async def _handle_cancel(self, ws, data):
        request_id = data.get("request_id", "")
        req = self.db.get(request_id)
        if not req:
            await _send(ws, ErrorEvent(code="not_found", message=f"Unknown request: {request_id}"))
            return
        if req["status"] != RequestStatus.RUNNING.value:
            await _send(ws, ErrorEvent(code="not_running", message=f"Request is {req['status']}, not running"))
            return

        task = self._running_tasks.get(request_id)
        if task:
            task.cancel()

    async def _handle_get_status(self, ws, data, client_id):
        project_id = data.get("project_id", "")
        requests = self.db.get_active(client_id, project_id)
        await _send(ws, StatusEvent(active_requests=[
            {
                "request_id": r["request_id"],
                "operation": r["operation"],
                "status": r["status"],
                "depends_on": json.loads(r["depends_on"] or "{}"),
                "output_dir": r["output_dir"],
            }
            for r in requests
        ]))

    async def _handle_get_log(self, ws, data):
        request_id = data.get("request_id", "")
        req = self.db.get(request_id)
        if not req:
            await _send(ws, ErrorEvent(code="not_found", message=f"Unknown request: {request_id}"))
            return

        log_text = req.get("log_text", "")
        progress_file = Path(req.get("output_dir", "")) / ".progress"
        if progress_file.exists():
            try:
                log_text += "\n" + progress_file.read_text()
            except OSError:
                pass

        await _send(ws, LogEvent(request_id=request_id, content=log_text))

    async def _handle_acknowledge(self, ws, data):
        request_id = data.get("request_id", "")
        req = self.db.get(request_id)
        if not req:
            await _send(ws, AcknowledgedEvent(request_id=request_id))
            return
        if req["status"] not in (RequestStatus.COMPLETED.value, RequestStatus.FAILED.value,
                                  RequestStatus.CRASHED.value):
            await _send(ws, ErrorEvent(code="invalid_state", message=f"Cannot acknowledge {req['status']} request"))
            return
        self.db.delete(request_id)
        await _send(ws, AcknowledgedEvent(request_id=request_id))

    async def _handle_reject(self, ws, data):
        request_id = data.get("request_id", "")
        req = self.db.get(request_id)
        if not req:
            await _send(ws, RejectedEvent(request_id=request_id))
            return
        _delete_dir(req.get("output_dir"))
        self.db.delete(request_id)
        await _send(ws, RejectedEvent(request_id=request_id))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _send_to_request(self, request_id: str, event):
        ws_id = self._request_ws.get(request_id)
        if ws_id is None:
            return
        ws = self._clients.get(ws_id)
        if ws and not ws.closed:
            await _send(ws, event)

    def shutdown(self):
        self._shutdown_event.set()


async def _send(ws: web.WebSocketResponse, event) -> None:
    try:
        await ws.send_str(to_json(event))
    except (ConnectionError, RuntimeError):
        pass


def _delete_dir(path: Optional[str]) -> None:
    if path and Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _ensure_env_path():
    """Ensure the Python env's bin dir is on PATH so external tools
    (COLMAP, ffmpeg, etc.) installed alongside Python are found."""
    import sys as _sys
    env_bin = str(Path(_sys.executable).resolve().parent)
    path = os.environ.get("PATH", "")
    if env_bin not in path.split(os.pathsep):
        os.environ["PATH"] = env_bin + os.pathsep + path
        logger.info("Added %s to PATH", env_bin)


def main():
    parser = argparse.ArgumentParser(description="Splatrix processing server")
    parser.add_argument("--socket", type=str, default=str(DEFAULT_SOCKET),
                        help="Unix domain socket path")
    parser.add_argument("--tcp", type=str, default=None,
                        help="TCP host:port (e.g. 0.0.0.0:8765)")
    parser.add_argument("--db", type=str,
                        default=str(Path.home() / ".splatrix" / "server.db"),
                        help="SQLite database path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    _ensure_env_path()

    tcp_host, tcp_port = None, None
    if args.tcp:
        parts = args.tcp.rsplit(":", 1)
        tcp_host = parts[0]
        tcp_port = int(parts[1]) if len(parts) > 1 else 8765

    server = SplatrixServer(
        db_path=Path(args.db),
        socket_path=Path(args.socket),
        tcp_host=tcp_host,
        tcp_port=tcp_port,
    )

    loop = asyncio.new_event_loop()

    def _handle_signal():
        logger.info("Shutting down...")
        server.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    loop.run_until_complete(server.start())
    loop.close()


if __name__ == "__main__":
    main()
