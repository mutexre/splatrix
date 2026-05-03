"""Workspace manager for staging server input/output.

Each server request gets two fresh UUID-named folders under
``~/.splatrix/workspace/``: one for input (client copies project data
into it) and one for output (server writes results into it).
"""

from __future__ import annotations

import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Iterable

WORKSPACE_ROOT = Path.home() / ".splatrix" / "workspace"


def _clonefile_available() -> bool:
    return platform.system() == "Darwin" and hasattr(os, "clonefile")


def _same_filesystem(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def clone_path(src: Path, dst: Path) -> None:
    """Copy *src* to *dst* using the fastest available method.

    On macOS APFS, ``os.clonefile`` is used (instant, copy-on-write,
    zero extra disk space).  Falls back to a regular copy elsewhere.
    """
    if src.is_dir():
        _clone_tree(src, dst)
    else:
        _clone_file(src, dst)


def _clone_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _clonefile_available():
        try:
            os.clonefile(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(str(src), str(dst))


def _clone_tree(src: Path, dst: Path) -> None:
    if _clonefile_available():
        try:
            os.clonefile(src, dst)
            return
        except OSError:
            pass
    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)


class WorkspaceManager:
    """Manages UUID-named staging folders under ``~/.splatrix/workspace/``."""

    def __init__(self, root: Path | None = None):
        self.root = root or WORKSPACE_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def create_folder(self) -> Path:
        """Create and return a fresh UUID-named folder."""
        folder = self.root / str(uuid.uuid4())
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def create_input_output(self) -> tuple[Path, Path]:
        """Create an input folder and an output folder, return both."""
        return self.create_folder(), self.create_folder()

    def clone_into(self, target_dir: Path, *sources: Path) -> None:
        """Clone (CoW or copy) each *source* into *target_dir*.

        Files are placed directly inside *target_dir*; directories are
        recreated with the same basename.
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in sources:
            dst = target_dir / src.name
            clone_path(src, dst)

    def cleanup_orphans(self, active_dirs: Iterable[str | Path]) -> int:
        """Delete workspace folders not in *active_dirs*.

        Returns the number of folders removed.
        """
        active = {str(Path(p).resolve()) for p in active_dirs}
        removed = 0
        if not self.root.exists():
            return 0
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            if str(entry.resolve()) not in active:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed

    def delete(self, folder: Path) -> None:
        """Delete a workspace folder if it exists."""
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
