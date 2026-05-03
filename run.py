#!/usr/bin/env python3
"""Launcher script for Splatrix.

Works in two modes:
  - Source checkout: resolves Qt paths from the PyQt6 package in the active env.
  - Frozen (.app bundle via PyInstaller): resolves Qt paths from sys._MEIPASS.
"""

import multiprocessing
import os
import sys


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _acquire_instance_lock():
    """Prevent multiple simultaneous instances using a file lock.
    Returns the lock file object (must stay alive for the process lifetime)
    or calls sys.exit if another instance holds the lock."""
    import fcntl
    lock_dir = os.path.join(os.path.expanduser("~"), ".splatrix")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, ".instance.lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Splatrix is already running.", file=sys.stderr)
        sys.exit(0)
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def _setup_frozen_env():
    """Configure paths when running inside a PyInstaller .app bundle."""
    base = sys._MEIPASS
    qt6_root = os.path.join(base, "PyQt6", "Qt6")
    qt6_plugins = os.path.join(qt6_root, "plugins")
    qt6_qml = os.path.join(qt6_root, "qml")
    qt6_lib = os.path.join(qt6_root, "lib")

    if os.path.isdir(qt6_plugins):
        os.environ["QT_PLUGIN_PATH"] = qt6_plugins
    if os.path.isdir(qt6_qml):
        os.environ["QML2_IMPORT_PATH"] = qt6_qml
    if os.path.isdir(qt6_lib):
        os.environ["DYLD_FRAMEWORK_PATH"] = qt6_lib


def _setup_source_env():
    """Configure paths when running from a source checkout / conda env."""
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        cuda_lib_path = os.path.join(conda_prefix, "lib")
        ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
        if cuda_lib_path not in ld_library_path:
            os.environ["LD_LIBRARY_PATH"] = f"{cuda_lib_path}:{ld_library_path}"

    try:
        import PyQt6
        _qt6_root = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6")
        _qt6_plugins = os.path.join(_qt6_root, "plugins")
        _qt6_qml = os.path.join(_qt6_root, "qml")
        _qt6_lib = os.path.join(_qt6_root, "lib")
        if os.path.isdir(_qt6_plugins):
            os.environ["QT_PLUGIN_PATH"] = _qt6_plugins
        if os.path.isdir(_qt6_qml):
            os.environ["QML2_IMPORT_PATH"] = _qt6_qml
        if os.path.isdir(_qt6_lib):
            os.environ["DYLD_FRAMEWORK_PATH"] = _qt6_lib
    except ImportError:
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()

    _instance_lock = _acquire_instance_lock()

    if _is_frozen():
        _setup_frozen_env()
    else:
        _setup_source_env()

    from splatrix.main_qml import main

    try:
        main()
    except Exception as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
