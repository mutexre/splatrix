"""Tests for splatrix.server — request lifecycle, crash recovery, cleanup."""

import json
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from splatrix.server import RequestDB, _delete_dir
from splatrix.protocol import RequestStatus


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    rdb = RequestDB(db_path)
    yield rdb
    rdb.close()


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _make_request(db, workspace, status="running", **overrides):
    """Insert a test request and create workspace dirs."""
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    req = {
        "request_id": overrides.get("request_id", "test-req-001"),
        "client_id": overrides.get("client_id", "test-client"),
        "project_id": overrides.get("project_id", "test-project"),
        "operation": overrides.get("operation", "data"),
        "status": status,
        "depends_on": json.dumps(overrides.get("depends_on", {})),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "params": json.dumps(overrides.get("params", {})),
        "started_at": overrides.get("started_at", datetime.now(timezone.utc).isoformat()),
        "completed_at": overrides.get("completed_at"),
    }
    db.insert_request(**req)
    return req


class TestRequestDB:
    def test_insert_and_get(self, db, workspace):
        req = _make_request(db, workspace)
        fetched = db.get("test-req-001")
        assert fetched is not None
        assert fetched["request_id"] == "test-req-001"
        assert fetched["status"] == "running"

    def test_update_status(self, db, workspace):
        _make_request(db, workspace)
        db.update_status("test-req-001", "completed", completed_at=datetime.now(timezone.utc).isoformat())
        req = db.get("test-req-001")
        assert req["status"] == "completed"

    def test_append_log(self, db, workspace):
        _make_request(db, workspace)
        db.append_log("test-req-001", "line 1\n")
        db.append_log("test-req-001", "line 2\n")
        req = db.get("test-req-001")
        assert "line 1" in req["log_text"]
        assert "line 2" in req["log_text"]

    def test_has_running(self, db, workspace):
        _make_request(db, workspace)
        assert db.has_running("test-client", "test-project")
        assert not db.has_running("other-client", "test-project")

    def test_get_active(self, db, workspace):
        _make_request(db, workspace, request_id="r1", status="running")
        ws2 = workspace / "ws2"
        ws2.mkdir()
        _make_request(db, ws2, request_id="r2", status="completed")
        active = db.get_active("test-client", "test-project")
        assert len(active) == 2

    def test_delete(self, db, workspace):
        _make_request(db, workspace)
        db.delete("test-req-001")
        assert db.get("test-req-001") is None

    def test_unique_running_per_client_project(self, db, workspace):
        _make_request(db, workspace, request_id="r1")
        ws2 = workspace / "ws2"
        ws2.mkdir()
        with pytest.raises(Exception):
            _make_request(db, ws2, request_id="r2")

    def test_different_project_can_run(self, db, workspace):
        _make_request(db, workspace, request_id="r1", project_id="proj1")
        ws2 = workspace / "ws2"
        ws2.mkdir()
        _make_request(db, ws2, request_id="r2", project_id="proj2")
        assert db.has_running("test-client", "proj1")
        assert db.has_running("test-client", "proj2")


class TestCrashRecovery:
    def test_mark_crashed(self, db, workspace):
        _make_request(db, workspace)
        crashed = db.mark_crashed()
        assert len(crashed) == 1
        assert crashed[0]["request_id"] == "test-req-001"
        req = db.get("test-req-001")
        assert req["status"] == "crashed"

    def test_completed_not_touched_on_crash_recovery(self, db, workspace):
        _make_request(db, workspace, status="completed",
                      completed_at=datetime.now(timezone.utc).isoformat())
        crashed = db.mark_crashed()
        assert len(crashed) == 0
        req = db.get("test-req-001")
        assert req["status"] == "completed"


class TestTimeoutCleanup:
    def test_stale_completed_cleaned(self, db, workspace):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        _make_request(db, workspace, status="completed", completed_at=old_time)
        stale = db.cleanup_stale(timedelta(hours=1))
        assert len(stale) == 1
        assert db.get("test-req-001") is None

    def test_recent_completed_not_touched(self, db, workspace):
        _make_request(db, workspace, status="completed",
                      completed_at=datetime.now(timezone.utc).isoformat())
        stale = db.cleanup_stale(timedelta(hours=1))
        assert len(stale) == 0
        assert db.get("test-req-001") is not None

    def test_stale_crashed_cleaned(self, db, workspace):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        _make_request(db, workspace, status="crashed", completed_at=old_time)
        stale = db.cleanup_stale(timedelta(hours=1))
        assert len(stale) == 1


class TestDeleteDir:
    def test_deletes_existing(self, tmp_path):
        d = tmp_path / "target"
        d.mkdir()
        (d / "file.txt").write_text("data")
        _delete_dir(str(d))
        assert not d.exists()

    def test_nonexistent_is_noop(self, tmp_path):
        _delete_dir(str(tmp_path / "nonexistent"))

    def test_none_is_noop(self):
        _delete_dir(None)
