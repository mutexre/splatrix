"""Tests for splatrix.workspace — UUID folder management and file cloning."""

import os
import platform
from pathlib import Path

import pytest

from splatrix.workspace import WorkspaceManager, clone_path


@pytest.fixture
def ws(tmp_path):
    return WorkspaceManager(root=tmp_path / "workspace")


class TestWorkspaceManager:
    def test_create_folder_returns_uuid_dir(self, ws):
        folder = ws.create_folder()
        assert folder.exists()
        assert folder.is_dir()
        assert folder.parent == ws.root

    def test_create_input_output_returns_two_folders(self, ws):
        inp, out = ws.create_input_output()
        assert inp.exists() and out.exists()
        assert inp != out

    def test_clone_into_files(self, ws, tmp_path):
        src_file = tmp_path / "video.mp4"
        src_file.write_text("fake video content")

        target = ws.create_folder()
        ws.clone_into(target, src_file)

        cloned = target / "video.mp4"
        assert cloned.exists()
        assert cloned.read_text() == "fake video content"

    def test_clone_into_directory(self, ws, tmp_path):
        src_dir = tmp_path / "data"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("aaa")
        (src_dir / "b.txt").write_text("bbb")

        target = ws.create_folder()
        ws.clone_into(target, src_dir)

        cloned_dir = target / "data"
        assert cloned_dir.is_dir()
        assert (cloned_dir / "a.txt").read_text() == "aaa"
        assert (cloned_dir / "b.txt").read_text() == "bbb"

    def test_cloned_file_is_independent(self, ws, tmp_path):
        """Modifying the clone should not affect the original."""
        src = tmp_path / "original.txt"
        src.write_text("original")

        target = ws.create_folder()
        ws.clone_into(target, src)

        clone = target / "original.txt"
        clone.write_text("modified")
        assert src.read_text() == "original"

    def test_cleanup_orphans_deletes_unreferenced(self, ws):
        keep = ws.create_folder()
        orphan = ws.create_folder()
        (orphan / "data.bin").write_bytes(b"\x00" * 100)

        removed = ws.cleanup_orphans([str(keep)])
        assert removed == 1
        assert keep.exists()
        assert not orphan.exists()

    def test_cleanup_orphans_with_empty_active(self, ws):
        a = ws.create_folder()
        b = ws.create_folder()
        removed = ws.cleanup_orphans([])
        assert removed == 2
        assert not a.exists()
        assert not b.exists()

    def test_delete_removes_folder(self, ws):
        folder = ws.create_folder()
        (folder / "file.txt").write_text("data")
        ws.delete(folder)
        assert not folder.exists()

    def test_delete_nonexistent_is_noop(self, ws):
        ws.delete(ws.root / "nonexistent-uuid")


class TestClonePath:
    def test_clone_file(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "dst.txt"
        clone_path(src, dst)
        assert dst.read_text() == "hello"

    def test_clone_directory(self, tmp_path):
        src = tmp_path / "srcdir"
        src.mkdir()
        (src / "inner.txt").write_text("inner")
        dst = tmp_path / "dstdir"
        clone_path(src, dst)
        assert (dst / "inner.txt").read_text() == "inner"

    @pytest.mark.skipif(
        not (platform.system() == "Darwin" and hasattr(os, "clonefile")),
        reason="APFS clonefile only on macOS with Python 3.12+",
    )
    def test_clonefile_used_on_macos(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("data")
        dst = tmp_path / "dst.txt"
        clone_path(src, dst)
        assert dst.read_text() == "data"
        assert os.stat(src).st_dev == os.stat(dst).st_dev
