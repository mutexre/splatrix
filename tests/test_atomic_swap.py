"""Tests for splatrix.atomic_swap — atomic directory/file swapping."""

import os
from pathlib import Path

import pytest

from splatrix.atomic_swap import atomic_swap, atomic_replace


class TestAtomicSwap:
    def test_swap_two_directories(self, tmp_path):
        a = tmp_path / "dir_a"
        b = tmp_path / "dir_b"
        a.mkdir()
        b.mkdir()
        (a / "file.txt").write_text("content_a")
        (b / "file.txt").write_text("content_b")

        atomic_swap(a, b)

        assert (a / "file.txt").read_text() == "content_b"
        assert (b / "file.txt").read_text() == "content_a"

    def test_swap_two_files(self, tmp_path):
        a = tmp_path / "file_a"
        b = tmp_path / "file_b"
        a.write_text("aaa")
        b.write_text("bbb")

        atomic_swap(a, b)

        assert a.read_text() == "bbb"
        assert b.read_text() == "aaa"

    def test_swap_preserves_content(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        for i in range(5):
            (a / f"a_{i}.txt").write_text(f"a_{i}")
            (b / f"b_{i}.txt").write_text(f"b_{i}")

        atomic_swap(a, b)

        for i in range(5):
            assert (a / f"b_{i}.txt").read_text() == f"b_{i}"
            assert (b / f"a_{i}.txt").read_text() == f"a_{i}"


class TestAtomicReplace:
    def test_replace_nonexistent_target(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        (src / "data.txt").write_text("new_data")
        dst = tmp_path / "target"

        atomic_replace(src, dst)

        assert dst.exists()
        assert (dst / "data.txt").read_text() == "new_data"
        assert not src.exists()

    def test_replace_existing_target(self, tmp_path):
        src = tmp_path / "source"
        dst = tmp_path / "target"
        src.mkdir()
        dst.mkdir()
        (src / "new.txt").write_text("new")
        (dst / "old.txt").write_text("old")

        atomic_replace(src, dst)

        assert (dst / "new.txt").read_text() == "new"
        # src now contains old data (from swap)
        assert src.exists()
        assert (src / "old.txt").read_text() == "old"

    def test_replace_file_target(self, tmp_path):
        src = tmp_path / "new.ply"
        dst = tmp_path / "output.ply"
        src.write_text("new_ply_data")
        dst.write_text("old_ply_data")

        atomic_replace(src, dst)

        assert dst.read_text() == "new_ply_data"
        assert src.read_text() == "old_ply_data"

    def test_replace_source_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            atomic_replace(tmp_path / "nonexistent", tmp_path / "target")

    def test_replace_leaves_original_on_failure(self, tmp_path):
        """If replacement fails mid-way, original should still be intact."""
        dst = tmp_path / "target"
        dst.mkdir()
        (dst / "important.txt").write_text("important")

        src = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            atomic_replace(src, dst)

        assert (dst / "important.txt").read_text() == "important"
