# =============================================================================
# Module: test_r1_daemon_acceptance.py
# Purpose: TESTER-FIRST red acceptance tests for R1 — resident embedding daemon.
#   Contract source: docs/architecture/0001-resident-embedding-daemon.md
#   (ADR 0001, SEALED commit dedfb0b), AC1-AC9 + INV-1..INV-4.
#   These REDS ARE THE CONTRACT for the coder build. Coder done == green.
#   Coder may NOT edit these tests without tester sign-off.
#
# Baseline shape: the daemon + client do NOT exist yet, so every test is RED now
#   ("plant current behavior, assert red, then coder greens"). Two tiers:
#
#   TIER A — deterministic (runs in CI, gates coder logic):
#     - Contract surface: embedding_daemon_client.embed(texts, op_type, config).
#     - AC5 skew, AC8 timeout, AC3 kill-9-mid-op → driven against a FAKE daemon
#       implementing the ADR wire protocol (length-prefixed framing) bound at the
#       ADR-fixed socket path under a temp HOME. Model-free protocol; fallback
#       uses the real central model (symlinked into temp HOME).
#     - INV-1 import boundary: the daemon server module imports NO search/cli/db.
#     - AC9 parity: daemon vector == inproc vector for a golden (model,text).
#
#   TIER B — live-path (real detached daemon + real model + ps/lsof):
#     - AC1 <100ms warm, AC2 one RSS copy, AC4 p95<500ms, AC6 idle unlink,
#       AC7 zero .db handles. Driven through the ADR-documented CLI verbs
#       (`memory embed daemon`, `memory meta health`) which do not exist yet →
#       RED now (unknown verb / nonzero exit). On a host WITHOUT the model these
#       skip (perf is unmeasurable); on the team host (model present) they RED.
#
# SEAM GAPS bounced to architect (see report): AC8 needs a configurable, SHORT
#   embed-timeout key (ADR says "configurable, default ~30s" but names no key);
#   this suite assumes config.embedding.daemon_embed_timeout_s — reconcile on
#   coder pairing. Daemon server module name assumed embedding_daemon_server.
# =============================================================================

from __future__ import annotations

import json
import os
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for the search integration path",
)

# Real central model — needed only by TIER A fallback + AC9 parity + TIER B perf.
# Resolved against the REAL home before any HOME monkeypatch.
_REAL_MODEL = Path(os.path.expanduser("~")) / ".memory" / "models" / "default.gguf"
requires_model = pytest.mark.skipif(
    not _REAL_MODEL.exists(),
    reason="real central embedding model (~/.memory/models/default.gguf) required",
)

SOCK_REL = Path(".memory") / "run" / "embedd.sock"
PID_REL = Path(".memory") / "run" / "embedd.pid"


# -----------------------------------------------------------------------------
# Wire helpers — ADR §"Wire protocol": 4-byte big-endian uint32 length + payload
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# Fake daemon — implements just enough of the ADR wire protocol to exercise the
# CLIENT's fallback contract deterministically, without a real model on the
# daemon side. `mode` selects the failure it injects after handshake.
# -----------------------------------------------------------------------------

class _FakeDaemon:
    def __init__(self, sock_path: Path, mode: str):
        self.sock_path = str(sock_path)
        self.mode = mode
        self._server = None
        self._thread = None

    def __enter__(self):
        mode = self.mode

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    _recv_frame(self.request)  # client handshake
                except Exception:
                    return
                if mode == "skew":
                    _send_frame(
                        self.request,
                        json.dumps({"ok": False, "err": "version_skew",
                                    "got": {"model_path": "/other/A.gguf"}}).encode(),
                    )
                    return
                # handshake OK for the remaining modes
                _send_frame(
                    self.request,
                    json.dumps({"ok": True, "model_path": "/fake/B.gguf",
                                "dims": 768, "n_threads": 2}).encode(),
                )
                try:
                    _recv_frame(self.request)  # embed request
                except Exception:
                    return
                if mode == "slow":
                    time.sleep(30)  # exceed any sane embed timeout → client bails
                elif mode == "truncate":
                    self.request.close()  # simulate kill -9 mid-op

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
            allow_reuse_address = True

        os.makedirs(os.path.dirname(self.sock_path), exist_ok=True)
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        self._server = Server(self.sock_path, Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass


# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_home(monkeypatch):
    """Isolated HOME so the socket + pidfile resolve under tmp. MUST be a SHORT
    path: the UDS at HOME/.memory/run/embedd.sock must stay under the AF_UNIX
    104-char limit (macOS) — pytest's tmp_path (~100 chars) blows it. Use a
    short /tmp dir. Symlink the real model in so inproc fallback still works."""
    import tempfile, shutil
    home = Path(tempfile.mkdtemp(prefix="mclit.", dir="/tmp"))
    monkeypatch.setenv("HOME", str(home))
    (home / ".memory" / "run").mkdir(parents=True, exist_ok=True)
    models = home / ".memory" / "models"
    models.mkdir(parents=True, exist_ok=True)
    if _REAL_MODEL.exists():
        try:
            (models / "default.gguf").symlink_to(_REAL_MODEL)
        except OSError:
            pass
    yield home
    shutil.rmtree(home, ignore_errors=True)


def _client():
    """The ADR client seam. Missing today → this IS the baseline-red."""
    try:
        from memory_cli.embedding import embedding_daemon_client as c
    except ModuleNotFoundError:
        pytest.fail(
            "R1 NOT IMPLEMENTED: memory_cli.embedding.embedding_daemon_client is "
            "missing (ADR 0001 client seam embedding_daemon_client.embed)."
        )
    return c


def _load_config():
    from memory_cli.config import load_config
    return load_config()


def _first_vec(result):
    """Accept either [768 floats] (flattened single) or [[768 floats]] (batch)."""
    if result and isinstance(result[0], (int, float)):
        return list(result)
    return list(result[0])


def _cli(args, home: Path, timeout=30):
    """Run the `memory` CLI as a real detached-capable subprocess with an
    isolated, cleared env (isolation discipline: env_clear + explicit vars)."""
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
    }
    return subprocess.run(
        [sys.executable, "-m", "memory_cli", *args],
        capture_output=True, text=True, env=env, timeout=timeout,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def _json(proc):
    """Parse the CLI JSON envelope; return the .data payload (or {} on miss)."""
    import json as _j
    try:
        obj = _j.loads(proc.stdout)
    except (ValueError, TypeError):
        return {}
    return obj.get("data", obj) if isinstance(obj, dict) else {}


# =============================================================================
# TIER A — deterministic contract reds
# =============================================================================

class TestClientContractSurface:
    def test_embed_callable_with_texts_op_type_config(self, temp_home):
        c = _client()
        assert hasattr(c, "embed"), "client must expose embed()"
        import inspect
        params = list(inspect.signature(c.embed).parameters)
        assert params[:3] == ["texts", "op_type", "config"], (
            f"embed signature {params} != (texts, op_type, config) per ADR"
        )


class TestAC5VersionSkewNeverServesWrongModelVectors:
    @requires_model
    def test_skew_daemon_forces_client_fallback_to_inproc_vector(self, temp_home):
        c = _client()
        sock = temp_home / SOCK_REL
        with _FakeDaemon(sock, mode="skew"):
            vec = _first_vec(c.embed(["what is a neuron"], "query", _load_config()))
        # Fell back to inproc: a real 768-dim L2-normalized vector for the B-query,
        # NOT the daemon's model-A response (which was refused at handshake).
        assert len(vec) == 768
        norm = sum(x * x for x in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-3, f"expected L2-normalized inproc vector, norm={norm}"


class TestAC8EmbedTimeoutFallsBackNoHang:
    @requires_model
    def test_slow_daemon_triggers_bounded_fallback(self, temp_home, monkeypatch):
        c = _client()
        cfg = _load_config()
        # SEAM GAP (bounced to architect): short configurable embed timeout.
        if hasattr(cfg.embedding, "daemon_embed_timeout_s"):
            monkeypatch.setattr(cfg.embedding, "daemon_embed_timeout_s", 2, raising=False)
        sock = temp_home / SOCK_REL
        t0 = time.perf_counter()
        with _FakeDaemon(sock, mode="slow"):
            vec = _first_vec(c.embed(["hello world"], "query", cfg))
        elapsed = time.perf_counter() - t0
        assert len(vec) == 768
        assert elapsed < 10.0, (
            f"embed did not fall back within the timeout window ({elapsed:.1f}s) — "
            "MUST-never-hang invariant (ADR fallback contract)"
        )


class TestAC3Kill9MidOpFallsBackCleanly:
    @requires_model
    def test_truncated_daemon_read_falls_back_no_traceback(self, temp_home):
        c = _client()
        sock = temp_home / SOCK_REL
        with _FakeDaemon(sock, mode="truncate"):
            # Must NOT raise: truncated read → inproc fallback, caller sees a vector.
            vec = _first_vec(c.embed(["mid-op kill"], "query", _load_config()))
        assert len(vec) == 768


class TestINV1DaemonImportBoundary:
    def test_daemon_server_imports_no_search_cli_db(self):
        # INV-1: daemon is EMBED-ONLY — imports no search/, cli/, db/ package.
        # Subprocess import so the check is on a clean interpreter.
        code = (
            "import importlib, sys\n"
            "importlib.import_module('memory_cli.embedding.embedding_daemon_server')\n"
            "bad = [m for m in sys.modules if m.startswith(('memory_cli.search',"
            "'memory_cli.cli','memory_cli.db'))]\n"
            "print('FORBIDDEN:' + ','.join(sorted(bad)))\n"
            "sys.exit(1 if bad else 0)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[2]), timeout=60,
        )
        assert proc.returncode == 0, (
            "daemon server module missing OR violates INV-1 (embed-only). "
            f"stdout={proc.stdout.strip()} stderr={proc.stderr.strip()[:300]}"
        )


class TestAC9DaemonInprocVectorParity:
    @requires_model
    def test_golden_daemon_vector_equals_inproc_vector(self):
        # INV-2 / AC9: for the same (model, text, op_type) the daemon's vector
        # must equal the inproc vector (deterministic embed).
        try:
            from memory_cli.embedding import embedding_daemon_server as srv
        except ModuleNotFoundError:
            pytest.fail(
                "R1 NOT IMPLEMENTED: memory_cli.embedding.embedding_daemon_server "
                "missing (ADR 0001 daemon) — cannot prove AC9 parity."
            )
        from memory_cli.embedding.model_loader_lazy_singleton import get_model
        from memory_cli.embedding.embed_single_and_batch import embed_single
        from memory_cli.config import load_config

        text = "the quick brown fox embeds deterministically"
        inproc = embed_single(get_model(load_config()), text, "query")
        # Daemon embed path (in-process call into the daemon's embed function).
        daemon_vec = srv.embed_texts([text], "query")[0]  # assumed server API
        assert len(daemon_vec) == len(inproc) == 768
        max_abs = max(abs(a - b) for a, b in zip(daemon_vec, inproc))
        assert max_abs < 1e-6, f"daemon vs inproc vector drift {max_abs} (AC9 parity)"


# =============================================================================
# TIER B — live-path reds (real detached daemon + real model + ps/lsof)
# Driven through the ADR CLI verbs, which do not exist yet → RED now.
# =============================================================================

def _daemon_up(home: Path) -> bool:
    h = _cli(["meta", "health"], home)
    return h.returncode == 0 and "up" in (h.stdout + h.stderr).lower()


@requires_model
class TestTierBLiveDaemon:
    def _start(self, home):
        r = _cli(["embed", "daemon", "--bg"], home)
        assert r.returncode == 0, (
            f"`memory embed daemon --bg` failed (verb missing today = RED). "
            f"rc={r.returncode} err={r.stderr.strip()[:200]}"
        )
        deadline = time.time() + 5
        while time.time() < deadline and not _daemon_up(home):
            time.sleep(0.1)
        assert _daemon_up(home), "daemon did not become healthy within 5s"

    def _stop(self, home):
        _cli(["embed", "daemon", "--stop"], home)

    def test_ac1a_warm_embed_roundtrip_under_100ms_GATE(self, temp_home):
        # AC1a (GATE, ADR 0001 rev 226bd93): the daemon's OWN contribution — the
        # embedding_daemon_client.embed round-trip — must be <100ms warm
        # (measured AROUND the client call, NOT the full CLI). ~16ms in practice.
        self._start(temp_home)
        try:
            from memory_cli.embedding import embedding_daemon_client as dc
            from memory_cli.config import load_config
            cfg = load_config()
            dc.embed(["warm up the resident model"], "query", cfg)  # prime (loads model)
            # Warm round-trips: take the best of a few to discard scheduler jitter.
            best_ms = None
            for _ in range(5):
                t0 = time.perf_counter()
                dc.embed(["gate lookup latency probe"], "query", cfg)
                ms = (time.perf_counter() - t0) * 1000
                best_ms = ms if best_ms is None else min(best_ms, ms)
            assert best_ms < 100.0, (
                f"AC1a GATE: warm daemon embed round-trip {best_ms:.1f}ms >= 100ms"
            )
        finally:
            self._stop(temp_home)

    def test_ac1b_full_cli_cold_wall_informational(self, temp_home):
        # AC1b (INFORMATIONAL, NOT a gate, ADR 0001 rev 226bd93): the full-CLI
        # cold-client wall is dominated by the Python interpreter + import floor
        # (~90ms) and lands ~300ms — this is a lazy-import follow-up, OUT of R1
        # scope. We MEASURE + record it and only guard against a gross blow-up,
        # deliberately NOT asserting the <100ms gate against the full CLI.
        self._start(temp_home)
        try:
            _cli(["neuron", "add", "warm the daemon"], temp_home)
            t0 = time.perf_counter()
            r = _cli(["search", "warm"], temp_home)
            wall_ms = (time.perf_counter() - t0) * 1000
            print(f"[AC1b informational] full-CLI cold-client search wall = {wall_ms:.0f}ms")
            assert r.returncode == 0
            # Loose sanity ceiling only (regression tripwire, NOT the 100ms gate).
            assert wall_ms < 3000.0, (
                f"AC1b: full-CLI wall {wall_ms:.0f}ms — gross regression well past "
                "the documented ~300ms floor"
            )
        finally:
            self._stop(temp_home)

    @pytest.mark.skipif(
        not os.environ.get("MEMORY_PERF_TESTS"),
        reason="HOST-SENSITIVE perf gate (backlog #74): measures 20 full-CLI "
        "subprocess searches (each ~300ms Python-startup floor per ADR AC1b, not "
        "the daemon's contribution) so p95<500ms reds under host load. Run with "
        "MEMORY_PERF_TESTS=1. Follow-up: rewrite to embed-wall p95 (mirror AC1a).",
    )
    def test_ac4_p95_20_searches_under_500ms(self, temp_home):
        self._start(temp_home)
        try:
            _cli(["neuron", "add", "p95 corpus entry"], temp_home)
            samples = []
            for _ in range(20):
                t0 = time.perf_counter()
                _cli(["search", "p95"], temp_home)
                samples.append((time.perf_counter() - t0) * 1000)
            samples.sort()
            p95 = samples[int(0.95 * len(samples)) - 1]
            assert p95 < 500.0, f"AC4: p95 {p95:.0f}ms >= 500ms"
        finally:
            self._stop(temp_home)

    def test_ac2_two_clients_one_resident_model_copy(self, temp_home):
        # UNQUARANTINED (#73 resolved by ADR R6 daemon introspection + flock).
        # Deterministic single-resident-copy via the LOCK-derived introspection
        # surface — no pgrep race. Start daemon → instance_count==1, rss≈140k;
        # a 2nd --bg returns already_up (lock held, no 2nd 139MB load); re-query
        # → instance_count still 1, rss unchanged. (Full form: test_r6_daemon_
        # introspection.py::TestDeterministicSingleInstance.)
        self._start(temp_home)
        try:
            st1 = _json(_cli(["embed", "daemon"], temp_home))
            assert st1.get("instance_count") == 1, f"AC2: instance_count != 1: {st1}"
            assert st1.get("rss_kb", 0) > 100_000, f"AC2: model not resident: {st1}"
            rss_before, pid_before = st1["rss_kb"], st1["pid"]

            r2 = _cli(["embed", "daemon", "--bg"], temp_home)
            assert _json(r2).get("state") == "already_up", (
                f"AC2: 2nd --bg not already_up (flock): {_json(r2)!r}"
            )

            st3 = _json(_cli(["embed", "daemon"], temp_home))
            assert st3.get("instance_count") == 1, f"AC2: instance_count changed: {st3}"
            assert st3.get("pid") == pid_before, "AC2: daemon respawned"
            assert st3.get("rss_kb") == rss_before, "AC2: rss changed = 2nd model copy"
        finally:
            self._stop(temp_home)

    def test_ac7_daemon_opens_zero_db_handles(self, temp_home):
        self._start(temp_home)
        try:
            pid = int((temp_home / PID_REL).read_text().split()[0])
            lsof = subprocess.run(
                ["lsof", "-p", str(pid)], capture_output=True, text=True
            )
            db_handles = [ln for ln in lsof.stdout.splitlines() if ".db" in ln]
            assert not db_handles, (
                f"AC7/INV-1: daemon holds .db handles (scope creep): {db_handles}"
            )
        finally:
            self._stop(temp_home)

    def test_ac6_idle_timeout_unlinks_socket_and_pidfile(self, temp_home, monkeypatch):
        # Start with a tiny idle timeout via env (ADR: idle_timeout configurable).
        monkeypatch.setenv("MEMORY_EMBED_IDLE_TIMEOUT_S", "1")
        self._start(temp_home)
        sock = temp_home / SOCK_REL
        pidf = temp_home / PID_REL
        deadline = time.time() + 8
        while time.time() < deadline and (sock.exists() or pidf.exists()):
            time.sleep(0.25)
        assert not sock.exists(), "AC6: socket leaked after idle_timeout"
        assert not pidf.exists(), "AC6: pidfile leaked after idle_timeout"
