#!/usr/bin/env python3
"""Launcher script for QML-based Video to Gaussian Splats Converter"""

import os
import sys

# Ensure CUDA libraries are in LD_LIBRARY_PATH for JIT compilation
conda_prefix = os.environ.get('CONDA_PREFIX')
if conda_prefix:
    cuda_lib_path = os.path.join(conda_prefix, 'lib')
    ld_library_path = os.environ.get('LD_LIBRARY_PATH', '')
    if cuda_lib_path not in ld_library_path:
        os.environ['LD_LIBRARY_PATH'] = f"{cuda_lib_path}:{ld_library_path}"

from splats.main_qml import main

if __name__ == "__main__":
    main()
