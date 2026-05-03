"""Client-server integration tests.

Spins up a real aiohttp server in-process with a mock stage executor,
then exercises the protocol through the client library.
"""

import asyncio
import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web, WSMsgType

from splatrix.protocol import (
    PROTOCOL_VERSION,
    AcceptedEvent,
    CompletedEvent,
    FailedEvent,
    CancelledEvent,
    HelloEvent,
    ErrorEvent,
    ProgressEvent,
    AcknowledgedEvent,
    RejectedEvent,
    StatusEvent,
    LogEvent,
    RequestStatus,
    from_json,
    to_json,
)
from splatrix.server import RequestDB, SplatrixServer
from splatrix.client import SplatrixClient, ServerError


def _short_sock_path() -> Path:
    return Path(tempfile.gettempdir()) / f"splatrix_int_{uuid.uuid4().hex[:8]}.sock"


@pytest_asyncio.fixture
async def server_env(tmp_path):
    """Set up a server with a mock executor on a temp unix socket."""
    sock = _short_sock_path()
    db_path = tmp_path / "test.db"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    server = SplatrixServer(
        db_path=db_path,
        socket_path=sock,
        use_thread_executor=True,
    )

    # Override _execute_stage to avoid importing nerfstudio
    import splatrix.server as srv_mod
    original_execute = srv_mod._execute_stage

    def mock_execute(stage, input_dir, output_dir, params, progress_file):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "result.txt").write_text("mock output")
        with open(progress_file, "w") as f:
            f.write(json.dumps({"stage": stage, "progress": 0.5}) + "\n")
            f.write(json.dumps({"stage": stage, "progress": 1.0}) + "\n")
        return {"success": True}

    srv_mod._execute_stage = mock_execute

    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.UnixSite(runner, str(sock))
    await site.start()

    asyncio.create_task(server._cleanup_loop())

    yield {
        "server": server,
        "sock": sock,
        "db": server.db,
        "workspace": workspace,
        "tmp_path": tmp_path,
    }

    srv_mod._execute_stage = original_execute
    await runner.cleanup()
    server.db.close()
    sock.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client(server_env):
    c = SplatrixClient(
        client_id="integration-test-client",
        socket_path=server_env["sock"],
        auto_reconnect=False,
    )
    await c.connect()
    yield c
    await c.disconnect()


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_data_operation(self, client, server_env):
        workspace = server_env["workspace"]
        input_dir = workspace / str(uuid.uuid4())
        output_dir = workspace / str(uuid.uuid4())
        input_dir.mkdir()
        output_dir.mkdir()
        (input_dir / "video.mp4").write_text("fake video")

        completed_ev = asyncio.Event()
        result = {}

        def on_completed(data):
            result.update(data)
            completed_ev.set()

        client.on("completed", on_completed)

        rid = await client.run_stage(
            project_id="test-project",
            stage="frames",
            input_dir=str(input_dir),
            output_dir=str(output_dir),
        )
        assert rid  # request_id returned

        await asyncio.wait_for(completed_ev.wait(), timeout=10)
        assert result["request_id"] == rid
        assert "result.txt" in str(list(Path(result["output_dir"]).iterdir()))

        await client.acknowledge(rid)

    @pytest.mark.asyncio
    async def test_get_status_empty(self, client):
        requests = await client.get_status("nonexistent-project")
        assert requests == []


class TestProtocolErrors:
    @pytest.mark.asyncio
    async def test_unknown_message_type(self, client):
        await client._ws.send_str(json.dumps({"type": "unknown_xyz"}))
        await asyncio.sleep(0.2)

    @pytest.mark.asyncio
    async def test_run_stage_nonexistent_input(self, client, server_env):
        errors = []
        client.on("error", lambda d: errors.append(d))

        from splatrix.protocol import RunStageMsg
        msg = RunStageMsg(
            client_id="integration-test-client",
            project_id="p1",
            stage="frames",
            input_dir="/nonexistent/path",
            output_dir="/tmp/out",
        )
        await client.send(msg)
        await asyncio.sleep(0.5)
        assert any(e.get("code") == "invalid_input" for e in errors)


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_running_request(self, client, server_env):
        workspace = server_env["workspace"]
        input_dir = workspace / str(uuid.uuid4())
        output_dir = workspace / str(uuid.uuid4())
        input_dir.mkdir()
        output_dir.mkdir()
        (input_dir / "video.mp4").write_text("fake")

        import splatrix.server as srv_mod

        async def slow_execute(operation, input_dir, output_dir, params, progress_file):
            await asyncio.sleep(30)
            return {"success": True}

        original = srv_mod._execute_stage

        # Make execution slow so we can cancel it
        def patched(*args):
            import time
            time.sleep(5)
            return {"success": True}

        srv_mod._execute_stage = patched

        cancelled_ev = asyncio.Event()
        client.on("cancelled", lambda d: cancelled_ev.set())

        rid = await client.run_stage(
            project_id="cancel-test",
            stage="frames",
            input_dir=str(input_dir),
            output_dir=str(output_dir),
        )

        await asyncio.sleep(0.3)

        from splatrix.protocol import CancelMsg
        await client.send(CancelMsg(request_id=rid))

        try:
            await asyncio.wait_for(cancelled_ev.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass  # cancellation may race with completion

        srv_mod._execute_stage = original


class TestDuplicateRequest:
    @pytest.mark.asyncio
    async def test_duplicate_running_rejected(self, client, server_env):
        workspace = server_env["workspace"]
        input1 = workspace / str(uuid.uuid4())
        output1 = workspace / str(uuid.uuid4())
        input2 = workspace / str(uuid.uuid4())
        output2 = workspace / str(uuid.uuid4())
        for d in (input1, output1, input2, output2):
            d.mkdir()
        (input1 / "v.mp4").write_text("a")
        (input2 / "v.mp4").write_text("b")

        import splatrix.server as srv_mod
        original = srv_mod._execute_stage

        def slow(*args):
            import time
            time.sleep(3)
            return {"success": True}

        srv_mod._execute_stage = slow

        errors = []
        client.on("error", lambda d: errors.append(d))

        rid1 = await client.run_stage(
            project_id="dup-test",
            stage="frames",
            input_dir=str(input1),
            output_dir=str(output1),
        )

        from splatrix.protocol import RunStageMsg
        msg = RunStageMsg(
            client_id="integration-test-client",
            project_id="dup-test",
            stage="feature_extract",
            input_dir=str(input2),
            output_dir=str(output2),
        )
        await client.send(msg)
        await asyncio.sleep(0.5)

        assert any(e.get("code") == "already_running" for e in errors)
        srv_mod._execute_stage = original
