# =============================================================================
# embed_noun_handler.py — `memory embed daemon` lifecycle + R6 introspection
# =============================================================================
# ADR 0001 R6: flock single-instance; thick status envelope; already_up on
# second --bg. meta health reuses probe_daemon_status() condensed block.
# =============================================================================

from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_cli.cli.entrypoint_and_argv_dispatch import register_noun
from memory_cli.cli.output_envelope_json_and_text import Result

SOCK_NAME = "embedd.sock"
PID_NAME = "embedd.pid"
STATE_NAME = "embedd.state"


def _run_dir() -> Path:
    d = Path.home() / ".memory" / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sock() -> Path:
    return _run_dir() / SOCK_NAME


def _pidfile() -> Path:
    return _run_dir() / PID_NAME


def _statefile() -> Path:
    return _run_dir() / STATE_NAME


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _rss_kb(pid: int) -> Optional[int]:
    try:
        r = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip())
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass
    return None


def _probe_lock_held() -> bool:
    """True if another process holds LOCK_EX on the pidfile (daemon up)."""
    pp = _pidfile()
    if not pp.exists():
        return False
    try:
        with open(pp, "r+") as fd:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            # We got the lock → no daemon holds it; release immediately.
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def _read_pidfile() -> tuple[Optional[int], Optional[float]]:
    """Return (pid, start_ts) from pidfile; start_ts may be None."""
    pp = _pidfile()
    if not pp.exists():
        return None, None
    try:
        lines = pp.read_text().strip().splitlines()
        pid = int(lines[0].split()[0]) if lines else None
        start_ts = float(lines[1]) if len(lines) > 1 else None
        return pid, start_ts
    except (ValueError, OSError):
        return None, None


def _read_statefile() -> dict:
    sf = _statefile()
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except (ValueError, OSError):
        return {}


def _handshake_meta() -> dict:
    """Best-effort UDS handshake for model_path/dims (skew-guard surface)."""
    sp = _sock()
    if not sp.exists():
        return {}
    try:
        from memory_cli.config import load_config
        from memory_cli.embedding.embedding_daemon_server import (
            PROTOCOL_V,
            _resolved_model_meta,
            _send_frame,
            _recv_frame,
        )
        cfg = load_config()
        path, mtime, dims = _resolved_model_meta(cfg)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect(str(sp))
            hs = {
                "v": PROTOCOL_V,
                "model_path": path,
                "model_mtime": mtime,
                "dims": dims,
            }
            _send_frame(sock, json.dumps(hs).encode())
            resp = json.loads(_recv_frame(sock).decode())
            if resp.get("ok"):
                return {
                    "model_path": resp.get("model_path", path),
                    "dims": resp.get("dims", dims),
                }
        finally:
            sock.close()
    except Exception:
        pass
    return {}


def probe_daemon_status() -> Dict[str, Any]:
    """Thick R6 status envelope (lock-derived instance_count, not pgrep)."""
    sp = _sock()
    pid, start_ts = _read_pidfile()
    lock_held = _probe_lock_held()
    state_blob = _read_statefile()

    if pid is None or not _pid_alive(pid):
        state = "down_stale" if pid is not None else "down"
        return {
            "state": state,
            "pid": None,
            "instance_count": 0,
            "rss_kb": None,
            "uptime_s": None,
            "model_path": state_blob.get("model_path"),
            "dims": state_blob.get("dims"),
            "socket": str(sp),
            "embed_count": int(state_blob.get("embed_count", 0)),
            "lock_held": False,
        }

    if not lock_held:
        # pid live but lock free → stale/zombie semantics
        return {
            "state": "down_stale",
            "pid": pid,
            "instance_count": 0,
            "rss_kb": _rss_kb(pid),
            "uptime_s": None,
            "model_path": state_blob.get("model_path"),
            "dims": state_blob.get("dims"),
            "socket": str(sp),
            "embed_count": int(state_blob.get("embed_count", 0)),
            "lock_held": False,
        }

    # Live + lock held → up (instance_count lock-derived == 1)
    # Prefer daemon-pinned rss_kb from statefile (stable across status polls;
    # detects real double-load via large jump if rewritten after 2nd model).
    rss = state_blob.get("rss_kb")
    if rss is None:
        rss = _rss_kb(pid)
    uptime = None
    if start_ts is not None:
        uptime = max(0.0, time.time() - start_ts)
    elif _pidfile().exists():
        try:
            uptime = max(0.0, time.time() - _pidfile().stat().st_mtime)
        except OSError:
            pass

    hs = _handshake_meta()
    model_path = hs.get("model_path") or state_blob.get("model_path")
    dims = hs.get("dims") if hs.get("dims") is not None else state_blob.get("dims")
    embed_count = int(state_blob.get("embed_count", 0))

    return {
        "state": "up",
        "pid": pid,
        "instance_count": 1,
        "rss_kb": rss,
        "uptime_s": uptime,
        "model_path": model_path,
        "dims": dims,
        "socket": str(sp),
        "embed_count": embed_count,
        "lock_held": True,
    }


def probe_daemon_condensed() -> Dict[str, Any]:
    """Condensed block for meta health: {state,pid,instance_count,rss_kb}."""
    full = probe_daemon_status()
    return {
        "state": full.get("state"),
        "pid": full.get("pid"),
        "instance_count": full.get("instance_count", 0),
        "rss_kb": full.get("rss_kb"),
    }


def handle_daemon(args: List[str], global_flags: Any) -> Any:
    """Start/stop/status the resident embedding daemon.

    Flags:
      --bg     start detached
      --stop   stop running daemon
      (none)   thick R6 status envelope
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

    # R6: if flock already held by a live daemon → already_up (no spawn, no model load)
    st = probe_daemon_status()
    if st.get("state") == "up" and st.get("lock_held") and st.get("instance_count") == 1:
        return Result(
            status="ok",
            data={
                "state": "already_up",
                "pid": st.get("pid"),
                "socket": str(sp),
                "instance_count": 1,
                "rss_kb": st.get("rss_kb"),
            },
        )

    # Stale only: clean pid/socket when lock NOT held
    if not _probe_lock_held():
        for path in (sp, pp, _statefile()):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

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
    deadline = time.time() + 60.0
    while time.time() < deadline:
        # Child may exit 0 immediately if it lost the flock race → already_up
        if proc.poll() is not None:
            st2 = probe_daemon_status()
            if st2.get("state") == "up":
                return Result(
                    status="ok",
                    data={
                        "state": "already_up",
                        "pid": st2.get("pid"),
                        "socket": str(sp),
                        "instance_count": 1,
                        "rss_kb": st2.get("rss_kb"),
                    },
                )
            # Child died without a live daemon — keep waiting? break to error
            if proc.returncode is not None and time.time() > deadline - 50:
                break
        st3 = probe_daemon_status()
        if st3.get("state") == "up" and sp.exists():
            return Result(
                status="ok",
                data={
                    "state": "started",
                    "pid": st3.get("pid"),
                    "socket": str(sp),
                    "instance_count": 1,
                    "rss_kb": st3.get("rss_kb"),
                },
            )
        time.sleep(0.1)
    return Result(
        status="error",
        error="daemon did not become ready within 60s",
    )


def _stop() -> Result:
    pp = _pidfile()
    sp = _sock()
    pid, _ = _read_pidfile()
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + 3.0
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    for path in (sp, pp, _statefile()):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    return Result(status="ok", data={"state": "stopped", "pid": pid})


def _status() -> Result:
    return Result(status="ok", data=probe_daemon_status())


_VERB_MAP = {
    "daemon": handle_daemon,
}

_VERB_DESCRIPTIONS = {
    "daemon": "Start/stop/status the resident embedding daemon (ADR 0001 R6)",
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
