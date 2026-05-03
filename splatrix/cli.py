"""Splatrix command-line interface.

Usage::

    splatrix server start|stop|status|logs|install|uninstall
    splatrix ping                           # test server connectivity
    splatrix run-stage DATA --project PATH --video PATH
    splatrix run-stage TRAINING --project PATH
    splatrix run-stage EXPORT --project PATH
    splatrix pipeline --project PATH --video PATH
    splatrix cancel --project PATH
    splatrix status --project PATH
    splatrix log REQUEST_ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from .protocol import Operation


def _load_config() -> dict:
    config_path = Path.home() / ".splatrix" / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def _ensure_client_id() -> str:
    config_path = Path.home() / ".splatrix" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = _load_config()
    if "client_id" not in config:
        try:
            import coolname
            config["client_id"] = coolname.generate_slug(3)
        except ImportError:
            import uuid
            config["client_id"] = str(uuid.uuid4())[:12]
        config_path.write_text(json.dumps(config, indent=2))
    return config["client_id"]


def _get_project_uuid(project_path: str) -> str:
    import yaml
    p = Path(project_path)
    proj_file = p / "project.yaml" if p.is_dir() else p
    if not proj_file.exists():
        print(f"Error: project not found at {proj_file}", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(proj_file.read_text())
    return data.get("project", {}).get("uuid", str(p.resolve()))


def _make_client(args):
    """Create a SplatrixClient from CLI args."""
    from .client import SplatrixClient
    client_id = _ensure_client_id()
    socket_path = Path(args.server)
    return SplatrixClient(
        client_id=client_id,
        socket_path=socket_path,
        auto_reconnect=False,
    )


# ---------------------------------------------------------------------------
# Server subcommand
# ---------------------------------------------------------------------------

def _cmd_server(args):
    from . import agent
    from .server import main as server_main

    action = args.action

    if action == "start":
        server_main()
    elif action == "stop":
        agent.uninstall()
        print("Server agent stopped")
    elif action == "status":
        s = agent.status()
        print(f"Installed: {s['installed']}")
        print(f"Running: {s['running']}")
        if s.get("detail"):
            print(f"Detail: {s['detail']}")
    elif action == "logs":
        log_dir = Path.home() / ".splatrix" / "logs"
        for log_file in sorted(log_dir.glob("server.*.log")):
            print(f"\n=== {log_file.name} ===")
            print(log_file.read_text()[-4096:])
    elif action == "install":
        path = agent.install()
        print(f"Installed service agent: {path}")
    elif action == "uninstall":
        agent.uninstall()
        print("Uninstalled service agent")


# ---------------------------------------------------------------------------
# Ping subcommand
# ---------------------------------------------------------------------------

def _cmd_ping(args):
    """Test connectivity to the server."""
    async def _run():
        from .client import SplatrixClient, ServerError
        client_id = _ensure_client_id()
        socket_path = Path(args.server)
        client = SplatrixClient(
            client_id=client_id, socket_path=socket_path, auto_reconnect=False,
        )
        t0 = time.monotonic()
        try:
            await client.connect()
            elapsed = (time.monotonic() - t0) * 1000
            from .protocol import PROTOCOL_VERSION
            print(f"Connected to server at {socket_path} ({elapsed:.0f}ms)")
            print(f"  Client ID:        {client_id}")
            print(f"  Protocol version: {PROTOCOL_VERSION}")
            await client.disconnect()
        except ConnectionError as e:
            print(f"Connection failed: {e}", file=sys.stderr)
            sys.exit(1)
        except ServerError as e:
            print(f"Server error: {e}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Run-stage subcommand
# ---------------------------------------------------------------------------

def _cmd_run_stage(args):
    client_id = _ensure_client_id()
    project_id = _get_project_uuid(args.project)
    stage = args.stage.lower()

    from .workspace import WorkspaceManager
    ws_mgr = WorkspaceManager()
    input_dir, output_dir = ws_mgr.create_input_output()

    print(f"Stage:      {stage}")
    print(f"Project:    {args.project}")
    print(f"Input dir:  {input_dir}")
    print(f"Output dir: {output_dir}")

    _STAGE_INPUT_SOURCES = {
        "frames":          lambda pd: Path(args.video) if args.video else None,
        "feature_extract": lambda pd: pd / "nerfstudio" / "frames",
        "feature_match":   lambda pd: pd / "nerfstudio" / "feature_extract",
        "reconstruction":  lambda pd: pd / "nerfstudio" / "feature_match",
        "training":        lambda pd: pd / "nerfstudio" / "nerfstudio_data",
        "export":          lambda pd: pd / "nerfstudio" / "outputs",
    }

    project_dir = Path(args.project)
    source_fn = _STAGE_INPUT_SOURCES.get(stage)
    source = source_fn(project_dir) if source_fn else None
    if source and source.exists():
        ws_mgr.clone_into(input_dir, source)
        print(f"Cloned input: {source} -> {input_dir}")
    elif stage == "frames":
        if not source or not source.exists():
            print("Error: --video is required for frames stage", file=sys.stderr)
            ws_mgr.delete(input_dir)
            ws_mgr.delete(output_dir)
            sys.exit(1)

    params = {}
    if args.iterations:
        params["max_iterations"] = args.iterations
    if args.frames:
        params["num_frames_target"] = args.frames

    async def _run():
        from .client import SplatrixClient
        socket_path = Path(args.server)
        client = SplatrixClient(
            client_id=client_id, socket_path=socket_path, auto_reconnect=False,
        )
        try:
            await client.connect()
        except ConnectionError as e:
            print(f"Cannot connect to server: {e}", file=sys.stderr)
            ws_mgr.delete(input_dir)
            ws_mgr.delete(output_dir)
            sys.exit(1)

        print(f"Connected as {client_id}")

        def _on_progress(data):
            s = data.get("stage", "")
            progress = data.get("progress", 0)
            bar = "█" * int(progress * 30) + "░" * (30 - int(progress * 30))
            print(f"\r  {s:20s} |{bar}| {progress*100:5.1f}%", end="", flush=True)

        client.on("progress", _on_progress)

        try:
            request_id = await client.run_stage(
                project_id=project_id,
                stage=stage,
                input_dir=str(input_dir),
                output_dir=str(output_dir),
                depends_on={},
                params=params,
            )
        except Exception as e:
            print(f"\nServer rejected request: {e}", file=sys.stderr)
            ws_mgr.delete(input_dir)
            ws_mgr.delete(output_dir)
            await client.disconnect()
            sys.exit(1)

        print(f"Request accepted: {request_id[:12]}...")

        completed = asyncio.Event()
        result = {}

        def _on_completed(data):
            if data.get("request_id") == request_id:
                result.update(data)
                completed.set()

        def _on_failed(data):
            if data.get("request_id") == request_id:
                result.update(data)
                result["_failed"] = True
                completed.set()

        def _on_cancelled(data):
            if data.get("request_id") == request_id:
                result["_cancelled"] = True
                completed.set()

        client.on("completed", _on_completed)
        client.on("failed", _on_failed)
        client.on("cancelled", _on_cancelled)

        await completed.wait()
        print()

        if result.get("_cancelled"):
            print("Stage was cancelled.")
            ws_mgr.delete(input_dir)
            ws_mgr.delete(output_dir)
        elif result.get("_failed"):
            print(f"Stage failed: {result.get('error', 'unknown')}")
            ws_mgr.delete(input_dir)
            ws_mgr.delete(output_dir)
        else:
            print(f"Completed. Output: {result.get('output_dir')}")
            await client.acknowledge(request_id)
            print("Acknowledged.")

            _STAGE_TARGETS = {
                "frames":          "nerfstudio/frames",
                "feature_extract": "nerfstudio/feature_extract",
                "feature_match":   "nerfstudio/feature_match",
                "reconstruction":  "nerfstudio/nerfstudio_data",
                "training":        "nerfstudio/outputs",
                "export":          "output.ply",
            }
            target_rel = _STAGE_TARGETS.get(stage)
            if target_rel:
                target = project_dir / target_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    shutil.rmtree(str(target), ignore_errors=True)
                shutil.move(str(output_dir), str(target))
                print(f"Output moved to: {target}")

        await client.disconnect()
        return not result.get("_failed") and not result.get("_cancelled")

    success = asyncio.run(_run())
    if not success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Pipeline subcommand
# ---------------------------------------------------------------------------

def _cmd_pipeline(args):
    """Run full pipeline: all 6 stages sequentially."""
    all_stages = ["frames", "feature_extract", "feature_match",
                  "reconstruction", "training", "export"]
    print("Pipeline: " + " → ".join(all_stages))
    for s in all_stages:
        print(f"\n{'='*50}")
        print(f"  Stage: {s}")
        print(f"{'='*50}")

        stage_args = argparse.Namespace(
            server=args.server,
            project=args.project,
            video=args.video,
            stage=s,
            iterations=args.iterations,
            frames=args.frames,
        )
        _cmd_run_stage(stage_args)

    print(f"\n{'='*50}")
    print("Pipeline complete!")


# ---------------------------------------------------------------------------
# Cancel subcommand
# ---------------------------------------------------------------------------

def _cmd_cancel(args):
    async def _run():
        client = _make_client(args)
        project_id = _get_project_uuid(args.project)

        try:
            await client.connect()
        except ConnectionError as e:
            print(f"Cannot connect: {e}", file=sys.stderr)
            sys.exit(1)

        requests = await client.get_status(project_id)
        running = [r for r in requests if r.get("status") == "running"]
        if not running:
            print("No running requests for this project")
        else:
            for r in running:
                rid = r["request_id"]
                print(f"Cancelling {rid[:12]}... ({r['operation']})")
                try:
                    await client.cancel(rid)
                    print(f"  Cancelled.")
                except Exception as e:
                    print(f"  Cancel failed: {e}")

        await client.disconnect()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Status subcommand
# ---------------------------------------------------------------------------

def _cmd_status(args):
    async def _run():
        client = _make_client(args)
        project_id = _get_project_uuid(args.project)

        try:
            await client.connect()
        except ConnectionError as e:
            print(f"Cannot connect: {e}", file=sys.stderr)
            sys.exit(1)

        requests = await client.get_status(project_id)
        if not requests:
            print("No active requests for this project")
        else:
            print(f"{'REQUEST ID':14s}  {'OPERATION':10s}  {'STATUS':10s}  OUTPUT")
            print("-" * 70)
            for r in requests:
                rid = r["request_id"][:12]
                print(f"{rid:14s}  {r['operation']:10s}  {r['status']:10s}  {r.get('output_dir', '')}")

        await client.disconnect()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Log subcommand
# ---------------------------------------------------------------------------

def _cmd_log(args):
    """Fetch log content for a request."""
    async def _run():
        from .client import ServerError
        client = _make_client(args)
        try:
            await client.connect()
        except ConnectionError as e:
            print(f"Cannot connect: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            content = await client.get_log(args.request_id)
            if content.strip():
                print(content)
            else:
                print("(no log content)")
        except ServerError as e:
            print(f"Error: {e}", file=sys.stderr)

        await client.disconnect()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="splatrix", description="Splatrix CLI")
    parser.add_argument("--server", type=str,
                        default=str(Path.home() / ".splatrix" / "server.sock"),
                        help="Server socket path")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")
    sub = parser.add_subparsers(dest="command")

    # server
    srv = sub.add_parser("server", help="Manage the processing server")
    srv.add_argument("action", choices=["start", "stop", "status", "logs", "install", "uninstall"])
    srv.set_defaults(func=_cmd_server)

    # ping
    sub.add_parser("ping", help="Test server connectivity").set_defaults(func=_cmd_ping)

    # run-stage
    rs = sub.add_parser("run-stage", help="Run a single pipeline stage")
    _stage_choices = [
        "frames", "feature_extract", "feature_match", "reconstruction",
        "training", "export",
        "FRAMES", "FEATURE_EXTRACT", "FEATURE_MATCH", "RECONSTRUCTION",
        "TRAINING", "EXPORT",
    ]
    rs.add_argument("stage", choices=_stage_choices, help="Stage to run")
    rs.add_argument("--project", required=True, help="Project directory")
    rs.add_argument("--video", help="Video file (for frames stage)")
    rs.add_argument("--iterations", type=int, help="Training iterations")
    rs.add_argument("--frames", type=int, help="Target number of frames")
    rs.set_defaults(func=_cmd_run_stage)

    # pipeline
    pl = sub.add_parser("pipeline", help="Run full pipeline (all 6 stages)")
    pl.add_argument("--project", required=True)
    pl.add_argument("--video", required=True)
    pl.add_argument("--iterations", type=int, default=30000)
    pl.add_argument("--frames", type=int, default=300)
    pl.set_defaults(func=_cmd_pipeline)

    # cancel
    cn = sub.add_parser("cancel", help="Cancel running operations")
    cn.add_argument("--project", required=True)
    cn.set_defaults(func=_cmd_cancel)

    # status
    st = sub.add_parser("status", help="Show active requests")
    st.add_argument("--project", required=True)
    st.set_defaults(func=_cmd_status)

    # log
    lg = sub.add_parser("log", help="Fetch log for a request")
    lg.add_argument("request_id", help="Request ID (full or prefix)")
    lg.set_defaults(func=_cmd_log)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
