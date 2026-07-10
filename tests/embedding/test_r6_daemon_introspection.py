# =============================================================================
# Module: test_r6_daemon_introspection.py
# Purpose: TESTER-FIRST red acceptance tests for ADR 0001 seam ruling R6 —
#   daemon introspection + flock single-instance (12caae7, backlog #73).
#   These REDS ARE THE CONTRACT for the daemon-introspection coder task.
#   Coder done == green; coder may NOT edit these tests without tester sign-off.
#   Landing these GREEN unquarantines AC2 (#73) as DETERMINISTIC.
#
# R6 contract:
#   - `memory embed daemon` (no flag) returns a THICK envelope:
#     {state, pid, instance_count, rss_kb, uptime_s, model_path, dims, socket,
#      embed_count, lock_held}. instance_count is LOCK-derived (flock), NOT pgrep.
#   - single-instance = fcntl.flock(pidfile, LOCK_EX|LOCK_NB) BEFORE model load;
#     a 2nd `--bg` returns {state: already_up} (lock held, no 2nd 139MB load).
#   - `memory meta health` gains a condensed {daemon: {state, pid,
#     instance_count, rss_kb}} block.
#
# Baseline: green x5 (honest-green-baseline task). Live-path: real detached
# daemon + real model; short /tmp HOME (AF_UNIX 104-char limit). Serial (one
# file, sequential) to avoid the llama.cpp double-load native crash (#73 root,
# which THIS feature fixes via flock).
# =============================================================================

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_REAL_MODEL = Path(os.path.expanduser("~")) / ".memory" / "models" / "default.gguf"
requires_model = pytest.mark.skipif(
    not _REAL_MODEL.exists(),
    reason="real central embedding model required for a live daemon",
)

# ON-DEMAND daemon lane: every test here spawns a REAL detached daemon + loads
# the 139MB model. Running many such tests in one pytest process triggers
# llama_cpp free_model native teardown contention (backlog #75), flaking the
# full suite. Gate the whole file behind MEMORY_DAEMON_TESTS so the DEFAULT
# `pytest tests/` is deterministic; run this coverage on demand:
#   MEMORY_DAEMON_TESTS=1 uv run pytest tests/embedding/test_r6_daemon_introspection.py
# Coverage is MOVED (not dropped) — see docs/testing-daemon-lane.md. #75 = real fix.
pytestmark = pytest.mark.skipif(
    not os.environ.get("MEMORY_DAEMON_TESTS"),
    reason="daemon on-demand lane (#75): set MEMORY_DAEMON_TESTS=1 to run real-daemon tests",
)

REPO = str(Path(__file__).resolve().parents[2])
STATUS_FIELDS = {
    "state", "pid", "instance_count", "rss_kb", "uptime_s",
    "model_path", "dims", "socket", "embed_count", "lock_held",
}


@pytest.fixture
def temp_home():
    home = Path(tempfile.mkdtemp(prefix="mclit-r6.", dir="/tmp"))
    (home / ".memory" / "run").mkdir(parents=True, exist_ok=True)
    models = home / ".memory" / "models"
    models.mkdir(parents=True, exist_ok=True)
    if _REAL_MODEL.exists():
        try:
            (models / "default.gguf").symlink_to(_REAL_MODEL)
        except OSError:
            pass
    yield home
    # Best-effort daemon stop + cleanup.
    try:
        _cli(["embed", "daemon", "--stop"], home)
    except Exception:
        pass
    import shutil
    shutil.rmtree(home, ignore_errors=True)


def _cli(args, home, timeout=30):
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    return subprocess.run(
        [sys.executable, "-m", "memory_cli", *args],
        capture_output=True, text=True, env=env, timeout=timeout, cwd=REPO,
    )


def _json(proc):
    """Parse the CLI JSON envelope; return the .data payload (or {} on miss)."""
    try:
        obj = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return {}
    return obj.get("data", obj) if isinstance(obj, dict) else {}


def _start(home):
    r = _cli(["embed", "daemon", "--bg"], home)
    assert r.returncode == 0, f"daemon --bg failed rc={r.returncode} err={r.stderr[:200]}"
    # Give the daemon time to acquire the lock, load the model, expose the socket.
    deadline = time.time() + 15
    while time.time() < deadline:
        st = _status(home)
        if st.get("state") == "up":
            return
        time.sleep(0.3)
    pytest.fail("daemon did not reach state=up within 15s")


def _status(home):
    return _json(_cli(["embed", "daemon"], home))  # no flag = status


# -----------------------------------------------------------------------------
# R6.1 — `memory embed daemon` status envelope has the full R6 shape
# -----------------------------------------------------------------------------

@requires_model
class TestStatusEnvelopeShape:
    def test_status_reports_all_r6_fields(self, temp_home):
        _start(temp_home)
        st = _status(temp_home)
        missing = STATUS_FIELDS - set(st.keys())
        assert not missing, (
            f"`memory embed daemon` status envelope missing R6 fields {sorted(missing)} "
            f"(got {sorted(st.keys())})"
        )
        assert st["state"] == "up"
        assert isinstance(st["pid"], int) and st["pid"] > 0
        assert st["socket"].endswith("embedd.sock")


# -----------------------------------------------------------------------------
# R6.2 — DETERMINISTIC single-instance (unquarantines AC2 #73)
# -----------------------------------------------------------------------------

@requires_model
class TestDeterministicSingleInstance:
    def test_second_bg_is_already_up_and_no_second_model_copy(self, temp_home):
        _start(temp_home)
        st1 = _status(temp_home)
        assert st1["instance_count"] == 1, f"expected instance_count 1, got {st1}"
        assert st1["rss_kb"] > 100_000, (
            f"resident model RSS {st1['rss_kb']}kb too small — model not loaded? {st1}"
        )
        rss_before = st1["rss_kb"]
        pid_before = st1["pid"]

        # A 2nd --bg must NOT double-load: lock held → already_up.
        r2 = _cli(["embed", "daemon", "--bg"], temp_home)
        st_2 = _json(r2)
        assert st_2.get("state") == "already_up", (
            f"2nd --bg did not report already_up (flock single-instance) — got {st_2!r} "
            f"stderr={r2.stderr[:150]!r}"
        )

        # Re-query: still exactly one instance, unchanged resident copy.
        st3 = _status(temp_home)
        assert st3["instance_count"] == 1, f"instance_count changed: {st3}"
        assert st3["pid"] == pid_before, f"daemon respawned {pid_before}->{st3['pid']}"
        assert st3["rss_kb"] == rss_before, (
            f"rss_kb changed {rss_before}->{st3['rss_kb']} — a second model copy loaded"
        )


# -----------------------------------------------------------------------------
# R6.3 — `memory meta health` condensed daemon block
# -----------------------------------------------------------------------------

@requires_model
class TestMetaHealthDaemonBlock:
    def test_meta_health_has_daemon_block(self, temp_home):
        _start(temp_home)
        health = _json(_cli(["meta", "health"], temp_home))
        assert "daemon" in health, (
            f"`meta health` has no daemon block (R6) — keys {sorted(health.keys())}"
        )
        d = health["daemon"]
        for k in ("state", "pid", "instance_count", "rss_kb"):
            assert k in d, f"meta health daemon block missing {k!r}: {d}"
        assert d["state"] == "up"
        assert d["instance_count"] == 1


# -----------------------------------------------------------------------------
# R6.4 — stale pidfile (dead pid) reads as down, not a false 'up'
# -----------------------------------------------------------------------------

@requires_model
class TestStalePidfileIsDown:
    def test_dead_pid_reports_down_stale(self, temp_home):
        _start(temp_home)
        pid = _status(temp_home)["pid"]
        _cli(["embed", "daemon", "--stop"], temp_home)
        # After stop the pid is gone; status must not claim 'up'.
        deadline = time.time() + 5
        state = None
        while time.time() < deadline:
            state = _status(temp_home).get("state")
            if state in ("down", "down_stale", None):
                break
            time.sleep(0.25)
        assert state in ("down", "down_stale"), (
            f"stopped daemon still reports state={state!r} (stale pid must read down)"
        )
