# =============================================================================
# Module: test_r1_daemon_fallback_integration.py
# Purpose: TESTER-FIRST red for R1 wiring at the search seam (ADR 0001).
#   The orchestrator's query-embed call
#   (light_search_pipeline_orchestrator.py ~ :552 `embed_single(...)`) must be
#   rerouted through embedding_daemon_client.embed (ADR "Client seam — the ONE
#   place the orchestrator switches"). Proves INV-3 (fallback is total): with
#   the daemon path forced unavailable, search still returns, exit 0.
#   REDS ARE THE CONTRACT — coder may not edit without tester sign-off.
#
# Baseline shape: today the orchestrator does NOT call the daemon client, so the
#   "client was invoked" assertion is RED now (wiring absent). Coder greens by
#   routing the seam through embedding_daemon_client.embed.
# =============================================================================

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.search.light_search_pipeline_orchestrator import (
    light_search,
    SearchOptions,
)


@pytest.fixture
def conn():
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 8)
    yield c
    c.close()


def _add(conn, content, ntype=None):
    from memory_cli.neuron import neuron_add
    attrs = {"type": ntype} if ntype else None
    return neuron_add(conn, content, attrs=attrs, no_embed=True)["id"]


class TestSearchSeamRoutesThroughDaemonClient:
    def test_semantic_query_embed_goes_through_daemon_client(self, conn):
        # A NON-facet query must take the embed path. That path must call the
        # daemon client (ADR client seam), not embed_single directly.
        _add(conn, "python asyncio tutorial")
        try:
            import memory_cli.embedding.embedding_daemon_client  # noqa: F401
        except ModuleNotFoundError:
            pytest.fail(
                "R1 NOT IMPLEMENTED: embedding_daemon_client missing — the "
                "orchestrator embed seam is not wired to the daemon (ADR 0001)."
            )
        with patch(
            "memory_cli.embedding.embedding_daemon_client.embed",
            return_value=[[0.0] * 768],
        ) as mock_embed:
            options = SearchOptions(query="python", fan_out_depth=0)
            light_search(conn, options)
        assert mock_embed.called, (
            "orchestrator did not route the query embed through "
            "embedding_daemon_client.embed (seam not wired)"
        )


class TestFallbackTotalityINV3:
    def test_daemon_unavailable_search_still_returns_exit_0(self, conn):
        # INV-3: any daemon failure → inproc fallback, CLI exit code unchanged.
        # Simulate the daemon client raising; search must still return exit 0
        # (BM25-only), never propagate the daemon error.
        _add(conn, "resilient search entry about verbs")
        try:
            import memory_cli.embedding.embedding_daemon_client  # noqa: F401
        except ModuleNotFoundError:
            pytest.fail(
                "R1 NOT IMPLEMENTED: embedding_daemon_client missing — cannot "
                "prove INV-3 total fallback at the search seam."
            )
        with patch(
            "memory_cli.embedding.embedding_daemon_client.embed",
            side_effect=RuntimeError("daemon exploded"),
        ):
            options = SearchOptions(query="verbs", fan_out_depth=0)
            envelope = light_search(conn, options)
        assert envelope.exit_code == 0, (
            "daemon failure broke search — INV-3 fallback is not total"
        )
