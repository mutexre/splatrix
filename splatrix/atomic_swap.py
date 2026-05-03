"""Atomic directory swap using OS-specific syscalls.

Provides ``atomic_swap(a, b)`` which atomically exchanges two directories
(or files), and ``atomic_replace(src, dst)`` which atomically replaces
*dst* with *src* (creating *dst* if it doesn't exist).

On macOS: ``renamex_np`` with ``RENAME_SWAP``
On Linux: ``renameat2`` with ``RENAME_EXCHANGE``
Cross-filesystem: copy to temp on target fs, then swap, then delete temp.
Fallback: ``shutil.move`` (non-atomic).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import shutil
import tempfile
from pathlib import Path

_system = platform.system()


# ---------------------------------------------------------------------------
# macOS: renamex_np(2)
# ---------------------------------------------------------------------------

_RENAME_SWAP = 0x00000002

def _renamex_np_swap(a: str, b: str) -> bool:
    """Attempt atomic swap via macOS ``renamex_np`` with RENAME_SWAP."""
    if _system != "Darwin":
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        ret = libc.renamex_np(a.encode(), b.encode(), ctypes.c_uint(_RENAME_SWAP))
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), a, None, b)
        return True
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Linux: renameat2(2)
# ---------------------------------------------------------------------------

_RENAME_EXCHANGE = 2
_SYS_RENAMEAT2 = {
    "x86_64": 316,
    "aarch64": 276,
    "armv7l": 382,
}

def _renameat2_exchange(a: str, b: str) -> bool:
    """Attempt atomic swap via Linux ``renameat2`` with RENAME_EXCHANGE."""
    if _system != "Linux":
        return False
    nr = _SYS_RENAMEAT2.get(platform.machine())
    if nr is None:
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        AT_FDCWD = -100
        ret = libc.syscall(
            nr,
            ctypes.c_int(AT_FDCWD), a.encode(),
            ctypes.c_int(AT_FDCWD), b.encode(),
            ctypes.c_uint(_RENAME_EXCHANGE),
        )
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), a, None, b)
        return True
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def atomic_swap(a: Path | str, b: Path | str) -> None:
    """Atomically exchange *a* and *b* (both must exist).

    After the call, the previous contents of *a* are at *b* and vice versa.
    Works on files and directories.
    """
    a_str, b_str = str(a), str(b)

    if _system == "Darwin" and _renamex_np_swap(a_str, b_str):
        return
    if _system == "Linux" and _renameat2_exchange(a_str, b_str):
        return

    # Fallback: three-step rename (NOT atomic — a brief window exists)
    tmp = str(a) + ".swap_tmp"
    os.rename(a_str, tmp)
    os.rename(b_str, a_str)
    os.rename(tmp, b_str)


def atomic_replace(src: Path | str, dst: Path | str) -> None:
    """Replace *dst* with *src*.

    If *dst* does not exist, a simple ``os.rename`` is used (atomic on
    the same filesystem).  If *dst* exists, an atomic swap is performed
    and the old contents (now at *src*) are left for the caller to clean up.

    If *src* and *dst* are on different filesystems, *src* is first
    copied to a temporary location on *dst*'s filesystem, then the swap
    (or rename) is done, and the temporary is cleaned up.
    """
    src, dst = Path(src), Path(dst)

    if not src.exists():
        raise FileNotFoundError(f"Source does not exist: {src}")

    same_fs = _same_fs(src, dst if dst.exists() else dst.parent)

    if not same_fs:
        # Copy to temp on the target filesystem, then swap/rename from there
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(dir=dst.parent, prefix=".swap_")
        local_src = Path(tmp_dir) / src.name
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(local_src))
            else:
                shutil.copy2(str(src), str(local_src))
            _do_replace(local_src, dst)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    _do_replace(src, dst)


def _do_replace(src: Path, dst: Path) -> None:
    """Replace *dst* with *src*, assuming same filesystem."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        atomic_swap(src, dst)
    else:
        os.rename(str(src), str(dst))


def _same_fs(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except FileNotFoundError:
        return True
