#!/usr/bin/env python3
"""Estimate total download size for bootstrap packages.

Queries PyPI JSON API and pip's dependency resolver to compute the full
download size including transitive dependencies.  Run this before shipping
to update the hardcoded sizeEstimate in bootstrapper.py.

Usage:
    python scripts/estimate-download-size.py [--platform PLATFORM]

Platforms: macos-arm64 (default), macos-x86_64, linux-x86_64, linux-x86_64-cuda
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGES = ["torch", "torchvision", "nerfstudio", "opencv-python-headless"]

CUDA_PACKAGES = ["torch", "torchvision"]
CUDA_INDEX = "https://download.pytorch.org/whl/cu121"


def resolve_sizes(packages: list[str], index_url: str = None) -> dict:
    """Use pip install --dry-run --report to get full dependency tree sizes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        report_path = f.name

    cmd = [
        sys.executable, "-m", "pip", "install",
        "--dry-run",
        "--report", report_path,
        "--ignore-installed",
        *packages,
    ]
    if index_url:
        cmd.extend(["--index-url", index_url])

    print(f"  Resolving: {' '.join(packages)}")
    if index_url:
        print(f"  Index: {index_url}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: pip resolve failed:\n{result.stderr[-500:]}", file=sys.stderr)
        Path(report_path).unlink(missing_ok=True)
        return {}

    with open(report_path) as f:
        report = json.load(f)
    Path(report_path).unlink(missing_ok=True)

    sizes = {}
    for item in report.get("install", []):
        name = item.get("metadata", {}).get("name", "unknown")
        url = item.get("download_info", {}).get("url", "")
        archive = item.get("download_info", {}).get("archive_info", {})
        size = archive.get("size")

        if size is None and url:
            size = _head_content_length(url)

        sizes[name] = {
            "size": size or 0,
            "url": url,
        }

    return sizes


def _head_content_length(url: str) -> int:
    """HTTP HEAD to get Content-Length for a URL."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.headers.get("Content-Length", 0))
    except Exception:
        return 0


def format_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.1f} GB"
    return f"{n / 1024**2:.0f} MB"


def estimate_platform(platform: str) -> int:
    """Estimate total download for a given platform. Returns bytes."""
    print(f"\n{'=' * 60}")
    print(f"Platform: {platform}")
    print(f"{'=' * 60}")

    total = 0

    if platform == "linux-x86_64-cuda":
        # PyTorch with CUDA — separate index
        print("\n── PyTorch (CUDA 12.1) ──")
        cuda_sizes = resolve_sizes(CUDA_PACKAGES, index_url=CUDA_INDEX)
        for name, info in sorted(cuda_sizes.items()):
            print(f"  {name:40s} {format_bytes(info['size']):>10s}")
            total += info["size"]

        # Remaining packages
        remaining = [p for p in PACKAGES if p not in CUDA_PACKAGES]
        print("\n── Other packages ──")
        other_sizes = resolve_sizes(remaining)
        for name, info in sorted(other_sizes.items()):
            if name not in cuda_sizes:
                print(f"  {name:40s} {format_bytes(info['size']):>10s}")
                total += info["size"]
    else:
        # All packages from default index
        print("\n── All packages ──")
        sizes = resolve_sizes(PACKAGES)
        for name, info in sorted(sizes.items()):
            print(f"  {name:40s} {format_bytes(info['size']):>10s}")
            total += info["size"]

    print(f"\n{'─' * 60}")
    print(f"  {'TOTAL':40s} {format_bytes(total):>10s}")
    return total


CONFIG_PATH = Path(__file__).parent.parent / "splatrix" / "bootstrap_config.json"


def _round_for_display(size_bytes: int) -> str:
    gb = size_bytes / (1024 ** 3)
    if gb >= 1.0:
        return f"~{round(gb * 2) / 2:.1f} GB"
    mb = size_bytes / (1024 ** 2)
    return f"~{round(mb / 100) * 100} MB"


def main():
    parser = argparse.ArgumentParser(description="Estimate bootstrap download size")
    parser.add_argument(
        "--platform",
        choices=["macos-arm64", "macos-x86_64", "linux-x86_64", "linux-x86_64-cuda", "all"],
        default="all",
    )
    args = parser.parse_args()

    if args.platform == "all":
        platforms = ["macos-arm64", "linux-x86_64-cuda"]
    else:
        platforms = [args.platform]

    results = {}
    for plat in platforms:
        results[plat] = estimate_platform(plat)

    # Build display strings
    rounded = {plat: _round_for_display(size) for plat, size in results.items()}

    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"{'=' * 60}")
    for plat, size in results.items():
        print(f"  {plat:30s} {format_bytes(size):>10s}  →  {rounded[plat]}")

    # Update config file
    config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            config = json.load(f)

    size_estimates = config.get("size_estimates", {})

    # Map platform results to config keys
    for plat, display in rounded.items():
        if "cuda" in plat:
            size_estimates["linux_cuda"] = display
        else:
            size_estimates["default"] = display

    config["size_estimates"] = size_estimates

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"\nUpdated {CONFIG_PATH}")


if __name__ == "__main__":
    main()
