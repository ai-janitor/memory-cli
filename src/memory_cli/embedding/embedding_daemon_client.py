# =============================================================================
# embedding_daemon_client.py — Client seam for the resident embed daemon
# =============================================================================
# Purpose: embedding_daemon_client.embed(texts, op_type, config) -> list[list[float]]
#   ALWAYS batch shape. On ANY daemon failure → inproc fallback (never hang).
#   ONE stderr warning per process on fallback (ADR 0001).
# =============================================================================

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any, List, Optional

from memory_cli.embedding.embed_single_and_batch import embed_batch
from memory_cli.embedding.model_loader_lazy_singleton import get_model

PROTOCOL_V = 1
SOCK_NAME = "embedd.sock"
PID_NAME = "embedd.pid"

_fallback_warned: bool = False


def _run_dir() -> Path:
    return Path.home() / ".memory" / "run"


def socket_path() -> Path:
    return _run_dir() / SOCK_NAME


def _env_or_config(env_key: str, cfg_val: float | int, cast=float):
    raw = os.environ.get(env_key)
    if raw is not None and raw != "":
        try:
            return cast(raw)
        except (TypeError, ValueError):
            pass
    return cfg_val


def _connect_timeout(config: Any) -> float:
    return float(
        _env_or_config(
            "MEMORY_EMBED_CONNECT_TIMEOUT_S",
            getattr(config.embedding, "daemon_connect_timeout_s", 2.0),
            float,
        )
    )


def _embed_timeout(config: Any) -> float:
    return float(
        _env_or_config(
            "MEMORY_EMBED_TIMEOUT_S",
            getattr(config.embedding, "daemon_embed_timeout_s", 30.0),
            float,
        )
    )


def _resolved_model_meta(config: Any) -> tuple[str, float, int]:
    central = Path.home() / ".memory" / "models" / "default.gguf"
    model_path = getattr(config.embedding, "model_path", None)
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


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("truncated read")
        buf += chunk
    return buf


def _recv_frame(sock: socket.socket) -> bytes:
    n = struct.unpack(">I", _recv_exact(sock, 4))[0]
    return _recv_exact(sock, n)


def _warn_fallback(reason: str) -> None:
    global _fallback_warned
    if _fallback_warned:
        return
    _fallback_warned = True
    msg = f"embed daemon unavailable ({reason}), using in-process load"
    print(msg, file=sys.stderr)
    warnings.warn(msg, stacklevel=3)


def _inproc_embed(texts: List[str], op_type: str, config: Any) -> List[List[float]]:
    model = get_model(config)
    return embed_batch(model, texts, op_type)  # type: ignore[arg-type]


def _try_autostart(config: Any) -> None:
    """Spawn `memory embed daemon --bg` once; ignore failures (fallback handles)."""
    try:
        env = os.environ.copy()
        # Detach: double-fork style via --bg handler; here just invoke CLI.
        subprocess.Popen(
            [sys.executable, "-m", "memory_cli", "embed", "daemon", "--bg"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except Exception:
        return
    # Poll socket ready ≤ ~3s
    sp = socket_path()
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if sp.exists():
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(0.2)
                s.connect(str(sp))
                s.close()
                return
            except OSError:
                pass
        time.sleep(0.05)


def _daemon_embed(
    texts: List[str],
    op_type: str,
    config: Any,
) -> List[List[float]]:
    """Talk to the daemon; raise on any failure so caller falls back."""
    path, mtime, dims = _resolved_model_meta(config)
    sp = socket_path()
    connect_t = _connect_timeout(config)
    embed_t = _embed_timeout(config)

    # Hygiene: single ownership of sock with finally-close on ALL paths
    # (incl. second-connect failure after autostart — was an fd leak).
    sock: Optional[socket.socket] = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(connect_t)
        try:
            sock.connect(str(sp))
        except OSError:
            try:
                sock.close()
            except OSError:
                pass
            sock = None
            # autostart-on-miss, retry once
            _try_autostart(config)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(connect_t)
            sock.connect(str(sp))

        # Handshake
        hs = {
            "v": PROTOCOL_V,
            "model_path": path,
            "model_mtime": mtime,
            "dims": dims,
        }
        _send_frame(sock, json.dumps(hs).encode())
        sock.settimeout(connect_t)
        resp = json.loads(_recv_frame(sock).decode())
        if not resp.get("ok"):
            err = resp.get("err", "handshake_failed")
            raise RuntimeError(f"daemon handshake: {err}")
        # Client-side split-brain check (even if server said ok)
        server_path = resp.get("model_path")
        if server_path is not None and Path(str(server_path)).resolve() != Path(path).resolve():
            raise RuntimeError("version_skew")

        # Embed request
        req = {
            "v": PROTOCOL_V,
            "op": "embed",
            "texts": list(texts),
            "op_type": op_type,
        }
        sock.settimeout(embed_t)
        _send_frame(sock, json.dumps(req).encode())

        # Response: status byte + ...
        status = _recv_exact(sock, 1)[0]
        if status != 0:
            # error: length-prefixed JSON
            n = struct.unpack(">I", _recv_exact(sock, 4))[0]
            err_body = _recv_exact(sock, n)
            raise RuntimeError(f"daemon embed error: {err_body!r}")

        count = struct.unpack(">I", _recv_exact(sock, 4))[0]
        d = struct.unpack(">I", _recv_exact(sock, 4))[0]
        blob = _recv_exact(sock, count * d * 4)
        vectors: List[List[float]] = []
        offset = 0
        for _ in range(count):
            vec = list(struct.unpack_from(f"<{d}f", blob, offset))
            offset += d * 4
            vectors.append(vec)
        return vectors
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def embed(texts: List[str], op_type: str, config: Any) -> List[List[float]]:
    """Embed texts via the resident daemon; ALWAYS return batch shape.

    On ANY failure (no socket, refused, timeout, skew, error, truncated read)
    fall back to in-process get_model + embed_batch. Never hang / crash caller.
    """
    if not texts:
        return []
    try:
        return _daemon_embed(list(texts), op_type, config)
    except Exception as exc:
        _warn_fallback(type(exc).__name__ + (f": {exc}" if str(exc) else ""))
        return _inproc_embed(list(texts), op_type, config)
