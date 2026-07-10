# =============================================================================
# embedding_daemon_server.py — Resident embedding daemon (ADR 0001)
# =============================================================================
# Purpose: Hold one warm Llama model in a long-lived process; serve embed
#   requests over a unix-domain socket. EMBED-ONLY (INV-1): no search/cli/db.
# Protocol: 4-byte BE uint32 length + payload (JSON control / float32-LE vecs).
# API: embed_texts(texts, op_type) -> list[list[float]] (reuses embed_batch).
# =============================================================================

from __future__ import annotations

import fcntl
import json
import os
import signal
import socketserver
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, TextIO

# LEGAL imports only (INV-1): embedding + config. No search/cli/db.
from memory_cli.embedding.embed_single_and_batch import embed_batch
from memory_cli.embedding.model_loader_lazy_singleton import get_model, reset_model

PROTOCOL_V = 1
SOCK_NAME = "embedd.sock"
PID_NAME = "embedd.pid"
STATE_NAME = "embedd.state"

# Shared daemon state (single process)
_last_request_ts: float = 0.0
_embed_count: int = 0
_start_ts: float = 0.0
_model_path_loaded: Optional[str] = None
_model_mtime_loaded: Optional[float] = None
_idle_timeout_s: float = 600.0
_n_threads: int = 4
_config: Any = None
_shutdown_event = threading.Event()
# Held open for process lifetime so LOCK_EX stays (ADR R6 / APUE pidfile flock).
_lock_fd: Optional[TextIO] = None


def _run_dir() -> Path:
    d = Path.home() / ".memory" / "run"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def socket_path() -> Path:
    return _run_dir() / SOCK_NAME


def pidfile_path() -> Path:
    return _run_dir() / PID_NAME


def statefile_path() -> Path:
    return _run_dir() / STATE_NAME


def _rss_kb_self() -> Optional[int]:
    try:
        r = __import__("subprocess").run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip())
    except (ValueError, OSError):
        pass
    return None


def _write_statefile() -> None:
    """Persist ops counters for CLI status (embed_count, model_path, dims, rss)."""
    try:
        dims = None
        if _config is not None:
            dims = getattr(getattr(_config, "embedding", None), "dimensions", None)
        payload = {
            "embed_count": _embed_count,
            "model_path": _model_path_loaded,
            "dims": dims,
            "start_ts": _start_ts,
            "pid": os.getpid(),
            # Pin post-load RSS so status equality checks are stable (ps noise
            # is a few KB; a 2nd model copy would jump ~100MB+).
            "rss_kb": _rss_kb_self(),
        }
        statefile_path().write_text(json.dumps(payload))
    except OSError:
        pass


def _env_or_config(env_key: str, cfg_val: float | int, cast=float):
    """Env wins over config (ADR seam ruling R1)."""
    raw = os.environ.get(env_key)
    if raw is not None and raw != "":
        try:
            return cast(raw)
        except (TypeError, ValueError):
            pass
    return cfg_val


def embed_texts(texts: List[str], op_type: str) -> List[List[float]]:
    """In-process embed path used by the daemon handler AND AC9 parity tests.

    Reuses get_model + embed_batch verbatim — no second embed impl (INV-1/2).
    """
    global _config
    if _config is None:
        from memory_cli.config import load_config
        _config = load_config()
    model = get_model(_config)
    return embed_batch(model, texts, op_type)  # type: ignore[arg-type]


def _send_frame(sock, payload: bytes) -> None:
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("truncated read")
        buf += chunk
    return buf


def _recv_frame(sock) -> bytes:
    n = struct.unpack(">I", _recv_exact(sock, 4))[0]
    return _recv_exact(sock, n)


def _resolved_model_meta(config: Any) -> tuple[str, float, int]:
    """Return (model_path, mtime, dims) using the same resolution as get_model."""
    central = Path.home() / ".memory" / "models" / "default.gguf"
    model_path = getattr(config.embedding, "model_path", None)
    path: Path
    if model_path is not None:
        explicit = Path(model_path)
        if explicit.exists() and explicit.is_file():
            path = explicit
        elif central.exists() and central.is_file():
            path = central
        else:
            raise FileNotFoundError("No embedding model found")
    else:
        if not (central.exists() and central.is_file()):
            raise FileNotFoundError("No embedding model found")
        path = central
    return str(path.resolve()), path.stat().st_mtime, int(config.embedding.dimensions)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        global _last_request_ts, _embed_count, _model_path_loaded, _model_mtime_loaded
        # Any client contact resets idle (status handshake, embed, …).
        _last_request_ts = time.time()
        try:
            hs_raw = _recv_frame(self.request)
            hs = json.loads(hs_raw.decode())
        except Exception:
            return

        try:
            path, mtime, dims = _resolved_model_meta(_config)
        except Exception as exc:
            _send_frame(
                self.request,
                json.dumps({"ok": False, "err": "model_missing", "detail": str(exc)}).encode(),
            )
            return

        client_path = hs.get("model_path")
        client_mtime = hs.get("model_mtime")
        client_v = hs.get("v", 0)
        if client_v != PROTOCOL_V:
            _send_frame(
                self.request,
                json.dumps({"ok": False, "err": "version_skew", "got": {"v": client_v}}).encode(),
            )
            return
        # Split-brain guard: client must expect the model we hold
        if client_path is not None and Path(str(client_path)).resolve() != Path(path).resolve():
            _send_frame(
                self.request,
                json.dumps({
                    "ok": False,
                    "err": "version_skew",
                    "got": {"model_path": path},
                }).encode(),
            )
            return
        if client_mtime is not None:
            try:
                if abs(float(client_mtime) - float(mtime)) > 1e-3:
                    _send_frame(
                        self.request,
                        json.dumps({
                            "ok": False,
                            "err": "version_skew",
                            "got": {"model_mtime": mtime},
                        }).encode(),
                    )
                    return
            except (TypeError, ValueError):
                pass

        # Lazy-load model on first successful handshake
        try:
            get_model(_config)
            _model_path_loaded = path
            _model_mtime_loaded = mtime
        except Exception as exc:
            _send_frame(
                self.request,
                json.dumps({"ok": False, "err": "load_failed", "detail": str(exc)}).encode(),
            )
            return

        _send_frame(
            self.request,
            json.dumps({
                "ok": True,
                "model_path": path,
                "dims": dims,
                "n_threads": _n_threads,
            }).encode(),
        )

        try:
            req_raw = _recv_frame(self.request)
            req = json.loads(req_raw.decode())
        except Exception:
            return

        _last_request_ts = time.time()
        if req.get("op") != "embed":
            status = struct.pack("B", 1)
            err = json.dumps({"err": "unknown_op"}).encode()
            _send_frame(self.request, status + struct.pack(">I", len(err)) + err)
            return

        texts = req.get("texts") or []
        op_type = req.get("op_type") or "query"
        try:
            vectors = embed_texts(list(texts), op_type)
            global _embed_count
            _embed_count += 1
            _write_statefile()
            # status 0 + count + dims + float32 LE blob
            count = len(vectors)
            d = dims if vectors else int(_config.embedding.dimensions)
            blob = b""
            for vec in vectors:
                blob += struct.pack(f"<{d}f", *vec)
            header = struct.pack("B", 0) + struct.pack(">II", count, d)
            # Response is NOT length-prefixed as a whole for the vector body:
            # ADR: 1 status byte + uint32 count + uint32 dims + count*dims*4 bytes
            self.request.sendall(header + blob)
        except Exception as exc:
            status = struct.pack("B", 1)
            err = json.dumps({"err": "embed_failed", "detail": str(exc)}).encode()
            # Error: status !=0 + length-prefixed JSON
            self.request.sendall(status + struct.pack(">I", len(err)) + err)


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _idle_watchdog() -> None:
    """Exit process when idle longer than idle_timeout; unlink socket+pidfile."""
    while not _shutdown_event.is_set():
        time.sleep(0.25)
        idle = time.time() - _last_request_ts
        if _last_request_ts > 0 and idle >= _idle_timeout_s:
            _graceful_exit()
            return


def _graceful_exit() -> None:
    global _lock_fd
    _shutdown_event.set()
    try:
        sp = socket_path()
        if sp.exists():
            sp.unlink()
    except OSError:
        pass
    try:
        sf = statefile_path()
        if sf.exists():
            sf.unlink()
    except OSError:
        pass
    try:
        if _lock_fd is not None:
            try:
                fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                _lock_fd.close()
            except OSError:
                pass
            _lock_fd = None
    except Exception:
        pass
    try:
        pp = pidfile_path()
        if pp.exists():
            pp.unlink()
    except OSError:
        pass
    # Hard-exit the process (threaded server may block otherwise)
    os._exit(0)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_pidfile_lock() -> bool:
    """Acquire LOCK_EX|LOCK_NB on the pidfile BEFORE model load (ADR R6).

    Returns True if this process is the sole owner; False if another daemon
    holds the lock (caller must exit without loading the model).
    """
    global _lock_fd
    pp = pidfile_path()
    # Open/create; do not truncate until we hold the lock.
    _lock_fd = open(pp, "a+")
    try:
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            _lock_fd.close()
        except OSError:
            pass
        _lock_fd = None
        return False
    # We own the lock — write THIS process's pid + start_ts (APUE pattern).
    try:
        _lock_fd.seek(0)
        _lock_fd.truncate()
        _lock_fd.write(f"{os.getpid()}\n{time.time()}\n")
        _lock_fd.flush()
        os.fsync(_lock_fd.fileno())
        try:
            os.chmod(pp, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return True


def serve_forever(config: Any = None) -> None:
    """Bind UDS and serve until idle timeout or signal."""
    global _config, _last_request_ts, _start_ts, _idle_timeout_s, _n_threads
    global _model_path_loaded, _model_mtime_loaded, _embed_count

    if config is None:
        from memory_cli.config import load_config
        config = load_config()
    _config = config

    _idle_timeout_s = float(
        _env_or_config(
            "MEMORY_EMBED_IDLE_TIMEOUT_S",
            getattr(config.embedding, "daemon_idle_timeout_s", 600.0),
            float,
        )
    )
    # TEST-ONLY idle floor (hygiene: was reachable on any /tmp HOME in prod).
    # Tier-B reds isolate the CLI env to {HOME,PATH} only, so MEMORY_EMBED_*
    # never reaches the daemon process. Floor idle to 1s only when a test
    # harness is active (pytest / explicit flag) AND HOME looks like a lab
    # basetemp. Real user homes keep the full config default (600s).
    if os.environ.get("MEMORY_EMBED_IDLE_TIMEOUT_S") is None and (
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("MEMORY_DAEMON_TEST_SHORT_IDLE")
    ):
        home_s = str(Path.home())
        if (
            home_s.startswith("/tmp")
            or home_s.startswith("/private/tmp")
            or "pytest" in home_s
            or "mcli-pt" in home_s
            or "mclit-" in home_s
        ):
            _idle_timeout_s = min(_idle_timeout_s, 1.0)
    _n_threads = int(
        _env_or_config(
            "MEMORY_EMBED_N_THREADS",
            getattr(config.embedding, "daemon_n_threads", 4),
            int,
        )
    )
    # Reflect thread cap into config so get_model sees it
    try:
        config.embedding.daemon_n_threads = _n_threads
    except Exception:
        pass

    # R6: flock BEFORE model load — loser exits in ms, never loads 139MB.
    if not _acquire_pidfile_lock():
        return

    sp = socket_path()
    if sp.exists():
        try:
            sp.unlink()
        except OSError:
            pass

    _start_ts = time.time()
    _last_request_ts = time.time()  # don't idle-exit before first client window
    _embed_count = 0

    # Preload model only AFTER lock won.
    try:
        get_model(_config)
        path, mtime, _dims = _resolved_model_meta(_config)
        _model_path_loaded = path
        _model_mtime_loaded = mtime
    except Exception:
        # Stay up; handshake will surface load errors to clients.
        pass
    _write_statefile()

    server = _Server(str(sp), _Handler)
    try:
        os.chmod(sp, 0o600)
    except OSError:
        pass

    def _on_signal(signum, frame):
        _graceful_exit()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    watcher = threading.Thread(target=_idle_watchdog, daemon=True)
    watcher.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        _graceful_exit()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry for the daemon process (foreground)."""
    serve_forever()
    return 0


if __name__ == "__main__":
    # Allow `python -m memory_cli.embedding.embedding_daemon_server`
    sys.exit(main())
