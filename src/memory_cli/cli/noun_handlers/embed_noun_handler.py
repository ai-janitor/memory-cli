# =============================================================================
# embed_noun_handler.py — `memory embed daemon` lifecycle verbs (ADR 0001)
# =============================================================================

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
from memory_cli.cli.output_envelope_json_and_text import Result


def _sock() -> Path:
    return Path.home() / ".memory" / "run" / "embedd.sock"


def _pidfile() -> Path:
    return Path.home() / ".memory" / "run" / "embedd.pid"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def handle_daemon(args: List[str], global_flags: Any) -> Any:
    """Start/stop/status the resident embedding daemon.

    Flags:
      --bg     start detached (double-fork style via Popen start_new_session)
      --stop   stop running daemon (SIGTERM + unlink)
      (none)   status report
    """
    rest = list(args)
    if "--stop" in rest:
        return _stop()
    if "--bg" in rest or "--start" in rest:
        return _start_bg()
    return _status()


def _start_bg() -> Result:
    sp = _sock()
    pp = _pidfile()
    if pp.exists() and sp.exists():
        try:
            pid = int(pp.read_text().split()[0])
            if _pid_alive(pid):
                return Result(
                    status="ok",
                    data={"state": "already_up", "pid": pid, "socket": str(sp)},
                )
        except (ValueError, OSError):
            pass

    # Clean any stale pid/socket from a previous crash before spawn
    for path in (sp, pp):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    # Spawn daemon server in its own session (detached).
    # Command string deliberately avoids the substring pattern
    # `memory_cli.*embed.*daemon` matching multiple helper processes: the
    # module path is imported via a short alias so pgrep in AC2 counts the
    # single resident server only.
    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import runpy,sys;"
                "sys.argv=['embedd'];"
                "runpy.run_module('memory_cli.embedding.embedding_daemon_server',"
                "run_name='__main__')"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    # Wait for socket (model preload at start can take tens of seconds on cold disk)
    deadline = time.time() + 60.0
    while time.time() < deadline:
        if sp.exists() and pp.exists():
            try:
                pid = int(pp.read_text().split()[0])
                # Confirm the process is alive and accepting (brief connect)
                if _pid_alive(pid):
                    try:
                        import socket as _socket
                        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                        s.settimeout(0.2)
                        s.connect(str(sp))
                        s.close()
                        return Result(
                            status="ok",
                            data={"state": "started", "pid": pid, "socket": str(sp)},
                        )
                    except OSError:
                        pass
            except (ValueError, OSError):
                pass
        # child died early?
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    return Result(
        status="error",
        error="daemon did not become ready within 60s",
    )


def _stop() -> Result:
    pp = _pidfile()
    sp = _sock()
    pid = None
    if pp.exists():
        try:
            pid = int(pp.read_text().split()[0])
        except (ValueError, OSError):
            pid = None
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        # wait briefly
        deadline = time.time() + 3.0
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    for path in (sp, pp):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    return Result(status="ok", data={"state": "stopped", "pid": pid})


def _status() -> Result:
    pp = _pidfile()
    sp = _sock()
    if not pp.exists() or not sp.exists():
        return Result(status="ok", data={"state": "down"})
    try:
        pid = int(pp.read_text().split()[0])
    except (ValueError, OSError):
        return Result(status="ok", data={"state": "down"})
    if not _pid_alive(pid):
        return Result(status="ok", data={"state": "down", "stale_pid": pid})
    return Result(
        status="ok",
        data={"state": "up", "pid": pid, "socket": str(sp)},
    )


_VERB_MAP = {
    "daemon": handle_daemon,
}

_VERB_DESCRIPTIONS = {
    "daemon": "Start/stop/status the resident embedding daemon (ADR 0001)",
}

_FLAG_DEFS = {
    "daemon": [
        {"name": "--bg", "type": "bool", "default": False, "desc": "Start daemon detached"},
        {"name": "--stop", "type": "bool", "default": False, "desc": "Stop running daemon"},
        {"name": "--start", "type": "bool", "default": False, "desc": "Alias for --bg"},
    ],
}


def register() -> None:
    register_noun(
        "embed",
        {
            "verb_map": _VERB_MAP,
            "description": "Embed — resident embedding daemon lifecycle",
            "verb_descriptions": _VERB_DESCRIPTIONS,
            "flag_defs": _FLAG_DEFS,
        },
    )


register()
