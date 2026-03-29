#!/usr/bin/env python3
"""Launcher script for Splatrix"""

import os
import sys

# Ensure CUDA libraries are in LD_LIBRARY_PATH for JIT compilation
conda_prefix = os.environ.get('CONDA_PREFIX')
if conda_prefix:
    cuda_lib_path = os.path.join(conda_prefix, 'lib')
    ld_library_path = os.environ.get('LD_LIBRARY_PATH', '')
    if cuda_lib_path not in ld_library_path:
        os.environ['LD_LIBRARY_PATH'] = f"{cuda_lib_path}:{ld_library_path}"

# When conda installs qt-main (e.g. via colmap), its Qt5 paths override
# PyQt6's Qt6 plugin path, causing "Could not find platform plugin cocoa".
# Fix by pointing QT_PLUGIN_PATH at PyQt6's own plugins before Qt loads.
try:
    import PyQt6
    _qt6_root = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6')
    _qt6_plugins = os.path.join(_qt6_root, 'plugins')
    _qt6_qml = os.path.join(_qt6_root, 'qml')
    _qt6_lib = os.path.join(_qt6_root, 'lib')
    if os.path.isdir(_qt6_plugins):
        os.environ['QT_PLUGIN_PATH'] = _qt6_plugins
    if os.path.isdir(_qt6_qml):
        os.environ['QML2_IMPORT_PATH'] = _qt6_qml
    if os.path.isdir(_qt6_lib):
        os.environ['DYLD_FRAMEWORK_PATH'] = _qt6_lib
except ImportError:
    pass

from splatrix.main_qml import main

if __name__ == "__main__":
    main()
