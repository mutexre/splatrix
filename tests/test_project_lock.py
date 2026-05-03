"""Tests for project locking via fcntl.flock."""

import multiprocessing
import os
import signal
import time
from pathlib import Path

import pytest

from splatrix.project_manager import ProjectManager, ProjectLockedError


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "test_project"
    d.mkdir()
    return d


def _try_lock_project(project_dir: str, result_queue):
    """Helper for subprocess: try to open a project, report success/failure."""
    pm = ProjectManager()
    try:
        pm.new_project(project_dir=project_dir)
        result_queue.put("locked")
        time.sleep(2)
        pm.close()
        result_queue.put("released")
    except ProjectLockedError:
        result_queue.put("blocked")
    except Exception as e:
        result_queue.put(f"error:{e}")


class TestProjectLocking:
    def test_acquire_lock_succeeds(self, project_dir):
        pm = ProjectManager()
        pm.new_project(project_dir=str(project_dir))
        assert pm.is_open
        assert (project_dir / ".lock").exists()
        pm.close()

    def test_second_instance_blocked(self, project_dir):
        pm1 = ProjectManager()
        pm1.new_project(project_dir=str(project_dir))

        pm2 = ProjectManager()
        with pytest.raises(ProjectLockedError):
            pm2.new_project(project_dir=str(project_dir))

        pm1.close()

    def test_lock_released_after_close(self, project_dir):
        pm1 = ProjectManager()
        pm1.new_project(project_dir=str(project_dir))
        pm1.close()

        pm2 = ProjectManager()
        pm2.new_project(project_dir=str(project_dir))
        assert pm2.is_open
        pm2.close()

    def test_lock_released_on_process_exit(self, project_dir):
        """When a process exits, its flock is released by the OS."""
        q = multiprocessing.Queue()
        p = multiprocessing.Process(target=_try_lock_project, args=(str(project_dir), q))
        p.start()

        result = q.get(timeout=5)
        assert result == "locked"
        p.terminate()
        p.join(timeout=5)

        pm = ProjectManager()
        pm.new_project(project_dir=str(project_dir))
        assert pm.is_open
        pm.close()

    def test_lock_file_does_not_block_load(self, project_dir):
        """Loading a project should also acquire the lock."""
        pm1 = ProjectManager()
        pm1.new_project(project_dir=str(project_dir))
        pm1.save_project()
        pm1.close()

        pm2 = ProjectManager()
        pm2.load_project(str(project_dir))
        assert pm2.is_open

        pm3 = ProjectManager()
        with pytest.raises(ProjectLockedError):
            pm3.load_project(str(project_dir))

        pm2.close()

    def test_reopen_after_close(self, project_dir):
        """Same ProjectManager can close and reopen."""
        pm = ProjectManager()
        pm.new_project(project_dir=str(project_dir))
        pm.save_project()
        pm.close()

        pm.load_project(str(project_dir))
        assert pm.is_open
        pm.close()
