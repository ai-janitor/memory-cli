# =============================================================================
# Module: test_r3_hard_timeout_self_reap.py
# Purpose: TESTER-FIRST red acceptance tests for R3 — hard per-query wall-clock
#   timeout + self-reap. Source: docs/perf-boost-recommendations.md:63-77 (R3),
#   minion #72 fix-4 (wedged searches 22h-31h; PIDs 20441/18334/11578).
#   These REDS ARE THE CONTRACT for the coder build. Coder done == green.
#   Coder may NOT edit these tests without tester sign-off.
#
# R3 ACCEPTANCE (baseline-FAIL shape — mechanism does NOT exist today):
#   - a wall-clock ceiling (default 120s, a flag raises it) wraps the whole
#     search + model load;
#   - on breach: kill llama.cpp work, emit a STRUCTURED error, exit != 0;
#   - the reap message names the STAGE reached (embed/bm25/vector/activation)
#     so the wedge is diagnosable;
#   - induced hang -> process exits AT the ceiling; no search PID older than the
#     ceiling survives (self-reap).
#
# Test tiers:
#   A deterministic in-process: induce a hang in a named stage, assert the
#     search is BOUNDED by a short ceiling, the error is structured + names the
#     stage, and teardown is clean (conn still usable — no WAL corruption).
#   B live-path subprocess: a real `memory search` process with an induced hang
#     must SELF-REAP at the ceiling (exit != 0), not wedge past it.
#
# SEAM GAPS bounced to lead/architect (see report): the ceiling FLAG name is
#   assumed `--timeout <seconds>` and the config/env default key is unspecified.
#   Reconcile on coder pairing; reds are the contract, seam-name changes route
#   through the tester.
# =============================================================================

from __future__ import annotations

import sys
import time
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_search
from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add

CEILING_S = 1          # short test ceiling passed via --timeout
HANG_S = 3             # induced stall > ceiling; a working reaper bounds us well under this
BOUND_S = 2.5          # a compliant reaper must return before this (ceiling + margin)


@pytest.fixture
def seeded_conn():
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 8)
    neuron_add(c, "python asyncio concurrency notes", no_embed=True)
    yield c
    c.close()


def _flags():
    return SimpleNamespace(config=None, db=None, global_only=False, format="json")


def _run_search_with_layer(conn, argv):
    """Drive handle_search with a single injected LOCAL store."""
    with patch(
        "memory_cli.cli.noun_handlers.db_connection_from_global_flags."
        "get_layered_connections_with_config",
        return_value=[(conn, object(), "LOCAL")],
    ):
        return handle_search(argv, _flags())


# -----------------------------------------------------------------------------
# A1 — induced hang is BOUNDED by the ceiling (MUST-not-wedge)
# -----------------------------------------------------------------------------

class TestInducedHangExitsAtCeiling:
    def test_embed_stage_hang_is_reaped_within_ceiling(self, seeded_conn):
        def _slow_model(_config):
            time.sleep(HANG_S)      # simulate a wedged model load / slow disk
            return MagicMock()

        t0 = time.perf_counter()
        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=_slow_model,
        ):
            _run_search_with_layer(seeded_conn, ["python", "--timeout", str(CEILING_S)])
        elapsed = time.perf_counter() - t0

        assert elapsed < BOUND_S, (
            f"search ran {elapsed:.1f}s with a {CEILING_S}s ceiling — the wall-clock "
            "reaper did not bound the wedge (R3 MUST-not-wedge)"
        )


# -----------------------------------------------------------------------------
# A2 — breach emits a STRUCTURED error, exit != 0, naming the stage reached
# -----------------------------------------------------------------------------

class TestReapErrorIsStructuredAndNamesStage:
    def test_embed_stage_reap_names_embed(self, seeded_conn):
        def _slow_model(_config):
            time.sleep(HANG_S)
            return MagicMock()

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=_slow_model,
        ):
            result = _run_search_with_layer(
                seeded_conn, ["python", "--timeout", str(CEILING_S)]
            )

        assert result.status == "error", "breach must surface a structured error"
        msg = (str(getattr(result, "error", "")) or "").lower()
        assert "timeout" in msg or "ceiling" in msg or "exceeded" in msg, (
            f"reap error not recognizable as a timeout: {msg!r}"
        )
        assert any(s in msg for s in ("embed", "model")), (
            f"reap error does not name the stage reached (embed/model): {msg!r}"
        )

    def test_vector_stage_reap_names_vector(self, seeded_conn):
        # Reach the vector stage: embed returns a valid unit vector, then the
        # vector retrieval wedges. The reap must name the VECTOR stage.
        def _slow_vectors(*_a, **_k):
            time.sleep(HANG_S)
            return []

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.embed_single",
            return_value=[1.0] + [0.0] * 767,
        ), patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            return_value=MagicMock(),
        ), patch(
            "memory_cli.search.light_search_pipeline_orchestrator.retrieve_vectors",
            side_effect=_slow_vectors,
        ):
            result = _run_search_with_layer(
                seeded_conn, ["python", "--timeout", str(CEILING_S)]
            )

        assert result.status == "error"
        msg = (str(getattr(result, "error", "")) or "").lower()
        assert "vector" in msg, f"reap error does not name the VECTOR stage: {msg!r}"


# -----------------------------------------------------------------------------
# A3 — the ceiling FLAG controls the limit (enforcement pairing):
#   same induced ~HANG_S stall in a timed stage →
#     * a LOW ceiling REAPS it (structured error)   [RED now: no reaper]
#     * a RAISED ceiling lets it FINISH (status ok)  [guard: stays green]
#   Proving BLOCK-first then pass, so the flag demonstrably drives the ceiling.
# -----------------------------------------------------------------------------

class TestCeilingFlagControlsLimit:
    def _slow_bm25_search(self, conn, timeout):
        # Full (non-facet) path with a valid unit embedding, but bm25 retrieval
        # stalls ~HANG_S inside the timed region.
        def _slow_bm25(*_a, **_k):
            time.sleep(HANG_S)
            return []

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.embed_single",
            return_value=[1.0] + [0.0] * 767,
        ), patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            return_value=MagicMock(),
        ), patch(
            "memory_cli.search.light_search_pipeline_orchestrator.retrieve_bm25",
            side_effect=_slow_bm25,
        ):
            return _run_search_with_layer(conn, ["python", "--timeout", str(timeout)])

    def test_low_ceiling_reaps_the_stall(self, seeded_conn):
        result = self._slow_bm25_search(seeded_conn, CEILING_S)
        assert result.status == "error", (
            "a stall longer than the low ceiling was NOT reaped — the --timeout "
            "flag does not drive the wall-clock ceiling"
        )

    def test_raised_ceiling_lets_the_same_stall_finish(self, seeded_conn):
        result = self._slow_bm25_search(seeded_conn, 120)
        assert result.status == "ok", (
            f"a stall well under the raised ceiling was reaped anyway: "
            f"status={result.status} err={getattr(result, 'error', None)!r}"
        )


# -----------------------------------------------------------------------------
# A4 — clean teardown after a reap: connection still usable (no WAL corruption)
# -----------------------------------------------------------------------------

class TestReapDoesNotCorruptConnection:
    def test_conn_usable_after_reap(self, seeded_conn):
        def _slow_model(_config):
            time.sleep(HANG_S)
            return MagicMock()

        with patch(
            "memory_cli.search.light_search_pipeline_orchestrator.get_model",
            side_effect=_slow_model,
        ):
            _run_search_with_layer(seeded_conn, ["python", "--timeout", str(CEILING_S)])

        # After the reap the same connection must still serve a normal query.
        follow = _run_search_with_layer(seeded_conn, ["python", "--type", "note"])
        assert follow.status == "ok", (
            "connection unusable after a reaped search — watchdog corrupted "
            "WAL/conn state (R3 RISK: clean teardown on kill)"
        )


# -----------------------------------------------------------------------------
# B — live-path: a real search process SELF-REAPS at the ceiling (exit != 0),
# so no search PID survives older than the ceiling.
# -----------------------------------------------------------------------------

class TestLivePathSelfReap:
    def test_wedged_process_self_reaps_at_ceiling(self, tmp_path):
        # Pre-build a real store file so the subprocess search actually REACHES
        # the embed stage (an empty store would exit before the wedge).
        db_path = tmp_path / "store.db"
        c = open_connection(str(db_path))
        load_and_verify_extensions(c)
        run_pending_migrations(c, 0, 8)
        neuron_add(c, "wedge target about python", no_embed=True)
        c.commit()
        c.close()

        # In-subprocess: wedge the BM25 stage (always executed, independent of
        # the embed daemon-vs-inproc branch) for 30s, then run a real `memory
        # search` with a short ceiling against the pre-built store. A compliant
        # build self-reaps (exit nonzero) near the ceiling; today it wedges →
        # our 8s harness timeout fires (RED).
        script = (
            "import sys, time\n"
            "from unittest.mock import patch\n"
            "patch('memory_cli.search.light_search_pipeline_orchestrator.retrieve_bm25',"
            " side_effect=lambda *a, **k: time.sleep(30)).start()\n"
            "from memory_cli.cli.entrypoint_and_argv_dispatch import main\n"
            f"main(['search','wedge','--db',{str(db_path)!r},'--timeout','{CEILING_S}'])\n"
        )
        env = {"HOME": str(tmp_path), "PATH": __import__("os").environ.get("PATH", "")}
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, env=env, timeout=8,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except subprocess.TimeoutExpired:
            pytest.fail(
                "search process did NOT self-reap at the ceiling — it wedged past "
                "8s (R3: no search PID older than the ceiling)"
            )
        elapsed = time.perf_counter() - t0
        assert proc.returncode != 0, (
            f"self-reaped search exited 0 (must be nonzero on breach). "
            f"stdout={proc.stdout[:150]!r} stderr={proc.stderr[:150]!r}"
        )
        assert elapsed < 6.0, f"self-reap took {elapsed:.1f}s — not bounded by ceiling"
        # Process-level structured reap message must name the timeout + the STAGE
        # reached (bm25 here) — diagnosability at the CLI boundary, not just in-proc.
        blob = (proc.stdout + proc.stderr).lower()
        assert "timeout" in blob, f"process reap message not a timeout: {blob[:200]!r}"
        assert "bm25" in blob, f"process reap message omits the stage reached: {blob[:200]!r}"
