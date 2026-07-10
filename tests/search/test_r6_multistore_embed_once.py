# =============================================================================
# Module: test_r6_multistore_embed_once.py
# Purpose: TESTER-FIRST red acceptance tests for R6 multistore embed-once
#   (perf-boost-recommendations.md:114-126 / NEW-3). Impl task-e0a61f52.
#   REDS ARE THE CONTRACT; coder greens without editing them.
#
# Today handle_search loops light_search PER store, each embedding the query
# independently → N embeds for N stores + each store hydrates its own full page
# before the cross-store merge truncates. R6 multistore:
#   1. embed the query ONCE, reuse the vector across same-config stores;
#   2. merge candidate lists BEFORE hydration → hydrate only the final page
#      (no hydration / access-write on rows the merge-truncate discards);
#   3. config-identity guard: if two stores' embed configs differ, fall back to
#      per-store embed (never reuse a vector across mismatched models).
#
# Mechanism: patch the daemon-client embed seam (the ONE embed entry the
# orchestrator uses) as a call-counter returning a fixed unit vector; inject two
# stores via get_layered_connections_with_config.
# =============================================================================

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add
from memory_cli.cli.noun_handlers.neuron_noun_handler import handle_search

_UNIT = [1.0] + [0.0] * 767
_EMBED_TARGET = "memory_cli.embedding.embedding_daemon_client.embed"
_HYDRATE_TARGET = "memory_cli.search.light_search_pipeline_orchestrator.hydrate_results"
_CONN_TARGET = (
    "memory_cli.cli.noun_handlers.db_connection_from_global_flags."
    "get_layered_connections_with_config"
)


def _store(contents):
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 10)
    for t in contents:
        neuron_add(c, t, no_embed=True)
    c.commit()
    return c


def _flags():
    return SimpleNamespace(config=None, db=None, global_only=False, format="json")


def _cfg(model_path="/central/default.gguf", dims=768):
    return SimpleNamespace(embedding=SimpleNamespace(model_path=model_path, dims=dims))


def _embed_counter():
    m = MagicMock(return_value=[list(_UNIT)])
    return m


# -----------------------------------------------------------------------------
# R6M.1 — two SAME-config stores embed the query exactly ONCE
# -----------------------------------------------------------------------------

class TestEmbedOnceAcrossStores:
    def test_two_stores_same_config_one_embed_call(self):
        local = _store(["python asyncio local note"])
        glob = _store(["python asyncio global note"])
        cfg = _cfg()  # identical config identity for both stores
        conns = [(local, cfg, "LOCAL"), (glob, cfg, "GLOBAL")]
        embed = _embed_counter()
        with patch(_CONN_TARGET, return_value=conns), patch(_EMBED_TARGET, embed):
            handle_search(["python"], _flags())
        assert embed.call_count == 1, (
            f"query embedded {embed.call_count}x across 2 same-config stores — "
            "R6 requires embed-once + reuse (was N-per-store)"
        )
        local.close(); glob.close()


# -----------------------------------------------------------------------------
# R6M.2 — hydrate only the final merged page, not every store's full page
# -----------------------------------------------------------------------------

class TestHydrateFinalPageOnly:
    def test_hydration_rows_equal_final_page_size(self):
        # Each store has 6 matches; a limit-5 search must hydrate the MERGED
        # top-5, not 6+6. Count neuron rows passed to hydrate_results.
        local = _store([f"python note L{i}" for i in range(6)])
        glob = _store([f"python note G{i}" for i in range(6)])
        cfg = _cfg()
        conns = [(local, cfg, "LOCAL"), (glob, cfg, "GLOBAL")]

        hydrated_counts = []
        from memory_cli.search import light_search_pipeline_orchestrator as orch
        real_hydrate = orch.hydrate_results

        def counting_hydrate(conn, paginated, *a, **k):
            hydrated_counts.append(len(paginated))
            return real_hydrate(conn, paginated, *a, **k)

        with patch(_CONN_TARGET, return_value=conns), \
             patch(_EMBED_TARGET, _embed_counter()), \
             patch(_HYDRATE_TARGET, counting_hydrate):
            handle_search(["python", "--limit", "5"], _flags())

        total_hydrated = sum(hydrated_counts)
        assert total_hydrated <= 5, (
            f"hydrated {total_hydrated} rows for a limit-5 search (per-store "
            f"hydration counts={hydrated_counts}) — R6 merges BEFORE hydration so "
            "rows discarded by merge-truncate are never hydrated/access-written"
        )
        local.close(); glob.close()


# -----------------------------------------------------------------------------
# R6M.3 — config-identity guard: differing embed configs → per-store embed
# -----------------------------------------------------------------------------

class TestConfigIdentityGuard:
    def test_differing_embed_configs_fall_back_to_per_store_embed(self):
        # If the two stores resolve DIFFERENT embed models, the query vector is
        # NOT reusable — the impl must embed per-store (never serve store B's
        # query with store A's model vector). Guards the embed-once optimization.
        local = _store(["python asyncio local note"])
        glob = _store(["python asyncio global note"])
        conns = [
            (local, _cfg(model_path="/models/A.gguf"), "LOCAL"),
            (glob, _cfg(model_path="/models/B.gguf"), "GLOBAL"),
        ]
        embed = _embed_counter()
        with patch(_CONN_TARGET, return_value=conns), patch(_EMBED_TARGET, embed):
            handle_search(["python"], _flags())
        assert embed.call_count == 2, (
            f"differing-config stores embedded {embed.call_count}x — must be 2 "
            "(per-store), never reuse one model's vector for another model's store"
        )
        local.close(); glob.close()
