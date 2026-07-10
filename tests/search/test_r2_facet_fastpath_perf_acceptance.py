# =============================================================================
# Module: test_r2_facet_fastpath_perf_acceptance.py
# Purpose: TESTER-FIRST red acceptance tests for R2 (implement task
#   task-7bff07294ff543ca93b0b6a3d5f23b3e). These REDS ARE THE CONTRACT —
#   coder R2 done == these green. Do NOT weaken.
#
# Source: docs/perf-boost-recommendations.md:38-58 (REC R2). R2 ACCEPTANCE:
#   - gate-lookup command < 300ms wall (facet fast-path serves --type/--tag
#     without --semantic — no llama.cpp model load).
#   - ZERO Llama() constructions during a facet gate-lookup.
#   - The facet fast-path run is RECORDED in search_latency so the perf win is
#     measurable (currently the fast-path returns before _record_latency at
#     light_search_pipeline_orchestrator.py — the R2 CLI patch adds recording).
#
# Contract map (see per-class docstrings for RED/GREEN status at authoring):
#   1. TestZeroLlamaConstruction — regression GUARD, GREEN NOW. Proves the
#      shipped facet fast-path constructs zero llama_cpp.Llama and that the
#      R2 latency-recording patch must NOT reintroduce a model load. Includes
#      a positive control so the zero-assert is provably non-vacuous.
#   2. TestFacetFastPathRecordsLatency — THE RED. Facet fast-path currently
#      returns before _record_latency, so search_latency stays empty. RED now,
#      GREEN after the coder wires latency recording onto the fast path.
#   3. TestGateLookupPerfSmoke — perf smoke. In-process facet gate-lookup wall
#      < 300ms. (Measures the light_search call, not full CLI cold-start.)
# =============================================================================

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full-schema migration (vec0 virtual table)",
)

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.search.light_search_pipeline_orchestrator import (
    light_search,
    SearchOptions,
)


# -----------------------------------------------------------------------------
# Fixtures — full schema (target v8) so the search_latency table (v007/v008)
# exists. A v001-only conn would silently swallow every latency insert.
# -----------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 8)  # full schema — includes search_latency
    yield c
    c.close()


def _add(conn, content, ntype=None, tags=None):
    """Seed a neuron via the production neuron_add() path with no_embed —
    the fast-path must work without any embedding ever having run."""
    from memory_cli.neuron import neuron_add
    attrs = {"type": ntype} if ntype else None
    result = neuron_add(conn, content, tags=tags, attrs=attrs, no_embed=True)
    return result["id"]


def _latency_row_count(conn):
    return conn.execute("SELECT COUNT(*) FROM search_latency").fetchone()[0]


# -----------------------------------------------------------------------------
# 1 — ZERO Llama() constructions on a facet gate-lookup
#
# Traces the ACTUAL constructor: llama_cpp.Llama is the sole model-construction
# site in the codebase (get_model() -> `from llama_cpp import Llama; Llama(...)`).
# Patching it counts every construction from ANY caller, incl. fleet callers —
# strictly stronger than mocking the orchestrator's local get_model ref.
#
# STATUS AT AUTHORING: GREEN — the shipped MEM-FIX-0007/0008 fast-path already
# skips embed on facet queries. This is a REGRESSION GUARD: it locks in the
# zero-Llama property so the R2 latency-recording patch cannot silently
# reintroduce a model load. The positive control below proves the counter is
# live (the zero-assert is not vacuous).
# -----------------------------------------------------------------------------

class TestZeroLlamaConstruction:
    def test_facet_gate_lookup_constructs_zero_llama(self, conn):
        # Realistic minion #72 gate-lookup shape: --type lesson, no --semantic.
        _add(conn, "lesson: verify on the live path before saying done", ntype="lesson")
        _add(conn, "lesson: dump known facts in briefs", ntype="lesson")
        _add(conn, "memory: unrelated build note", ntype="memory")

        with patch("llama_cpp.Llama") as mock_llama:
            options = SearchOptions(query="verify", ntype="lesson", limit=8)
            envelope = light_search(conn, options)

        assert mock_llama.call_count == 0, (
            f"facet gate-lookup constructed {mock_llama.call_count} Llama model(s); "
            "acceptance requires ZERO"
        )
        assert envelope.facet_fast is True
        assert envelope.exit_code == 0

    def test_positive_control_plain_search_does_construct_llama(self, conn):
        # Non-facet semantic search MUST reach the constructor — proves the
        # llama_cpp.Llama patch actually observes constructions, so the
        # zero-count assertion above genuinely constrains behavior.
        from memory_cli.embedding import model_loader_lazy_singleton as _ml
        _ml.reset_model()  # clear any singleton loaded by an earlier test

        _add(conn, "python programming tutorial about verbs")

        # Make the constructor cheap + non-fatal: a bare stub instead of a
        # 4GB model load. We assert only that construction was ATTEMPTED.
        with patch("llama_cpp.Llama", return_value=MagicMock()) as mock_llama:
            options = SearchOptions(query="python", fan_out_depth=0)
            light_search(conn, options)

        assert mock_llama.call_count >= 1, (
            "plain (non-facet) search did not construct a Llama model — the "
            "zero-Llama guard above would be vacuous"
        )
        _ml.reset_model()  # leave the singleton clean for other tests


# -----------------------------------------------------------------------------
# 2 — THE RED: facet fast-path run is recorded in search_latency
#
# The perf win is only measurable if the fast-path records its latency. Today
# _facet_fast_search() returns before _record_latency(), so search_latency
# stays empty for facet queries. The R2 CLI patch must record it (riding the
# same sampling/batch gate as R4 — must NOT reintroduce a raw per-call heavy
# write, and must NOT reintroduce a Llama load; guarded by class 1).
#
# STATUS AT AUTHORING: RED — asserts a row is written; none is today.
# -----------------------------------------------------------------------------

class TestFacetFastPathRecordsLatency:
    def test_facet_fastpath_records_a_latency_row(self, conn):
        _add(conn, "lesson: verify on the live path", ntype="lesson")

        assert _latency_row_count(conn) == 0  # baseline: nothing recorded yet

        with patch("llama_cpp.Llama") as mock_llama:
            options = SearchOptions(query="verify", ntype="lesson", limit=8)
            envelope = light_search(conn, options)

        assert envelope.facet_fast is True  # confirm the fast-path served it
        assert mock_llama.call_count == 0    # ...and did so with zero model load
        assert _latency_row_count(conn) == 1, (
            "facet fast-path did not record a search_latency row — the perf win "
            "is invisible to search_latency-based health reporting (R2 requires "
            "the fast-path be recorded)"
        )


# -----------------------------------------------------------------------------
# 3 — Perf smoke: in-process facet gate-lookup wall < 300ms
#
# Measures the light_search() call for the minion #72 gate-lookup shape
# (--type lesson --limit 8). This is the in-process facet-path cost, NOT full
# CLI process cold-start; the CLI-level < 300ms wall acceptance is verified
# separately on the live path. min-of-N discards scheduler jitter.
#
# STATUS AT AUTHORING: GREEN-expected (in-memory facet path is sub-ms) — this
# is a floor guard against a regression that reintroduces embed/vector cost.
# -----------------------------------------------------------------------------

class TestGateLookupPerfSmoke:
    def test_facet_gate_lookup_under_300ms(self, conn):
        for i in range(50):
            _add(conn, f"lesson number {i}: verify facts on the live path", ntype="lesson")

        best_ms = None
        with patch("llama_cpp.Llama"):  # a model load here would be an instant fail
            for _ in range(5):
                t0 = time.perf_counter()
                options = SearchOptions(query="verify", ntype="lesson", limit=8)
                envelope = light_search(conn, options)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                best_ms = elapsed_ms if best_ms is None else min(best_ms, elapsed_ms)

        assert envelope.facet_fast is True
        assert envelope.exit_code == 0
        assert best_ms < 300.0, (
            f"facet gate-lookup best wall {best_ms:.1f}ms exceeded the 300ms "
            "acceptance bound"
        )
