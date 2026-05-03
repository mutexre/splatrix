"""Service agent management — launchd (macOS) and systemd (Linux).

Generates plist/unit files so the processing server can run as a
persistent user daemon that starts on login and restarts on crash.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

SPLATRIX_DIR = Path.home() / ".splatrix"
SERVICE_LABEL = "io.github.mutexre.splatrix-server"


def _server_python() -> str:
    """Path to the Python interpreter in the bootstrapped env."""
    env_python = SPLATRIX_DIR / "envs" / "splatrix" / "bin" / "python"
    if env_python.exists():
        return str(env_python)
    return sys.executable


def _server_module() -> str:
    return "splatrix.server"


# ---------------------------------------------------------------------------
# macOS — launchd
# ---------------------------------------------------------------------------

def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def _launchd_plist_content() -> str:
    python = _server_python()
    socket = SPLATRIX_DIR / "server.sock"
    log_dir = SPLATRIX_DIR / "logs"
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{SERVICE_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{python}</string>
                <string>-m</string>
                <string>{_server_module()}</string>
                <string>--socket</string>
                <string>{socket}</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <dict>
                <key>SuccessfulExit</key>
                <false/>
            </dict>
            <key>StandardOutPath</key>
            <string>{log_dir / "server.out.log"}</string>
            <key>StandardErrorPath</key>
            <string>{log_dir / "server.err.log"}</string>
            <key>WorkingDirectory</key>
            <string>{SPLATRIX_DIR}</string>
        </dict>
        </plist>
    """)


def install_launchd() -> Path:
    plist = _launchd_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    (SPLATRIX_DIR / "logs").mkdir(parents=True, exist_ok=True)
    plist.write_text(_launchd_plist_content())
    subprocess.run(["launchctl", "load", str(plist)], check=True)
    return plist


def uninstall_launchd() -> None:
    plist = _launchd_plist_path()
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)], check=False)
        plist.unlink(missing_ok=True)


def status_launchd() -> dict:
    result = subprocess.run(
        ["launchctl", "list", SERVICE_LABEL],
        capture_output=True, text=True,
    )
    running = result.returncode == 0
    return {"installed": _launchd_plist_path().exists(), "running": running, "detail": result.stdout.strip()}


# ---------------------------------------------------------------------------
# Linux — systemd user unit
# ---------------------------------------------------------------------------

def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "splatrix-server.service"


def _systemd_unit_content() -> str:
    python = _server_python()
    socket = SPLATRIX_DIR / "server.sock"
    return dedent(f"""\
        [Unit]
        Description=Splatrix Processing Server
        After=default.target

        [Service]
        Type=simple
        ExecStart={python} -m {_server_module()} --socket {socket}
        Restart=on-failure
        RestartSec=5
        WorkingDirectory={SPLATRIX_DIR}

        [Install]
        WantedBy=default.target
    """)


def install_systemd() -> Path:
    unit = _systemd_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_systemd_unit_content())
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "splatrix-server.service"], check=True)
    return unit


def uninstall_systemd() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", "splatrix-server.service"], check=False)
    unit = _systemd_unit_path()
    unit.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def status_systemd() -> dict:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "splatrix-server.service"],
        capture_output=True, text=True,
    )
    return {
        "installed": _systemd_unit_path().exists(),
        "running": result.stdout.strip() == "active",
        "detail": result.stdout.strip(),
    }


# ---------------------------------------------------------------------------
# Cross-platform dispatch
# ---------------------------------------------------------------------------

def install() -> Path:
    if platform.system() == "Darwin":
        return install_launchd()
    elif platform.system() == "Linux":
        return install_systemd()
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")


def uninstall() -> None:
    if platform.system() == "Darwin":
        uninstall_launchd()
    elif platform.system() == "Linux":
        uninstall_systemd()
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")


def status() -> dict:
    if platform.system() == "Darwin":
        return status_launchd()
    elif platform.system() == "Linux":
        return status_systemd()
    else:
        return {"installed": False, "running": False, "detail": "Unsupported platform"}
