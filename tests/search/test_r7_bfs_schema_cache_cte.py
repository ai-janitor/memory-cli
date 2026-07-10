# =============================================================================
# Module: test_r7_bfs_schema_cache_cte.py
# Purpose: TESTER-FIRST red acceptance tests for R7 (perf-fix-plan #2) — BFS
#   PRAGMA-per-node + N+1 edge queries. REDS ARE THE CONTRACT; coder no edits.
#
# Today spreading_activation_bfs_linear_decay._get_neighbors:
#   - calls _has_confidence_column() (PRAGMA table_info(edges)) on EVERY node;
#   - issues 2 SELECTs per node (outgoing :295 + incoming :302).
# Over K visited nodes that is O(K) PRAGMAs + O(K) edge SELECTs. R7:
#   1. resolve the confidence column ONCE per search → PRAGMA count ≤ 1;
#   2. batch neighbor fetch per BFS LEVEL → edge-query count = O(depth), NOT
#      O(frontier width);
#   3. PARITY: the batched CTE preserves the fan-out set + hop_distance +
#      max-activation-wins visited logic (:245) — identical result.
#
# Mechanism: sqlite set_trace_callback counts PRAGMA + `FROM edges WHERE`
# statements. Deterministic; no model/embedding needed (facet/BM25 seed).
# =============================================================================

from __future__ import annotations

import time

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite_vec required for search path")

from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations
from memory_cli.neuron import neuron_add
from memory_cli.config import load_config
from memory_cli.search.light_search_pipeline_orchestrator import light_search, SearchOptions

_PRAGMA_RE = "pragma table_info(edges)"
_EDGE_RE = "from edges where"


def _conn():
    c = open_connection(":memory:")
    load_and_verify_extensions(c)
    run_pending_migrations(c, 0, 10)
    return c


def _edge(conn, src, dst, reason="relates_to", weight=1.0):
    now = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (src, dst, weight, reason, now),
    )


def _build_graph(conn, width, grandchildren_per_child=1):
    """Seed 'python root' matched by query 'python', fanning out to `width`
    children, each with `grandchildren_per_child` grandchildren (depth 2)."""
    seed = neuron_add(conn, "python root topic", no_embed=True)["id"]
    for i in range(width):
        child = neuron_add(conn, f"child node {i} about graphs", no_embed=True)["id"]
        _edge(conn, seed, child)
        for g in range(grandchildren_per_child):
            gc = neuron_add(conn, f"grandchild {i}.{g}", no_embed=True)["id"]
            _edge(conn, child, gc)
    conn.commit()
    return seed


def _trace_counts(conn, options):
    stmts = []
    conn.set_trace_callback(stmts.append)
    env = light_search(conn, options, config=load_config())
    conn.set_trace_callback(None)
    low = [s.lower() for s in stmts]
    pragma = sum(1 for s in low if _PRAGMA_RE in s)
    edges = sum(1 for s in low if _EDGE_RE in s)
    return env, pragma, edges


# -----------------------------------------------------------------------------
# R7.1 — PRAGMA table_info(edges) runs at most ONCE per search
# -----------------------------------------------------------------------------

class TestPragmaOncePerSearch:
    def test_confidence_column_probed_at_most_once(self):
        conn = _conn()
        _build_graph(conn, width=6, grandchildren_per_child=1)  # ~13 visited nodes
        _, pragma, _ = _trace_counts(conn, SearchOptions(query="python", fan_out_depth=2))
        assert pragma <= 1, (
            f"PRAGMA table_info(edges) ran {pragma}x for one search — R7 resolves "
            "the confidence column ONCE per search, not per BFS node"
        )
        conn.close()


# -----------------------------------------------------------------------------
# R7.2 — edge-query count is O(depth), NOT O(frontier width)
# -----------------------------------------------------------------------------

class TestEdgeQueriesScaleWithDepthNotWidth:
    def test_edge_query_count_independent_of_frontier_width(self):
        narrow = _conn()
        _build_graph(narrow, width=3, grandchildren_per_child=1)
        _, _, narrow_edges = _trace_counts(narrow, SearchOptions(query="python", fan_out_depth=2))
        narrow.close()

        wide = _conn()
        _build_graph(wide, width=12, grandchildren_per_child=1)
        _, _, wide_edges = _trace_counts(wide, SearchOptions(query="python", fan_out_depth=2))
        wide.close()

        assert wide_edges == narrow_edges, (
            f"edge-query count grows with frontier width (narrow={narrow_edges}, "
            f"wide={wide_edges}) — R7 batches neighbor fetch per BFS level so the "
            "count is O(depth), independent of how many nodes are in the frontier"
        )


# -----------------------------------------------------------------------------
# R7.3 — PARITY guard: batched CTE preserves fan-out set + hop_distance
#   (green NOW; locks the max-activation-wins topology through the refactor).
# -----------------------------------------------------------------------------

class TestFanOutParity:
    def test_fanout_set_and_hop_distance_preserved(self):
        conn = _conn()
        seed = _build_graph(conn, width=3, grandchildren_per_child=1)
        env = light_search(conn, SearchOptions(query="python", fan_out_depth=2),
                           config=load_config())
        # Map id -> hop_distance for every returned neuron.
        hops = {r["id"]: r.get("hop_distance") for r in env.results}

        # Seed is a direct match (hop 0). Children are hop 1, grandchildren hop 2.
        assert hops.get(seed) == 0, f"seed hop_distance != 0: {hops.get(seed)}"
        children = [r["id"] for r in env.results if r.get("hop_distance") == 1]
        grandchildren = [r["id"] for r in env.results if r.get("hop_distance") == 2]
        assert len(children) == 3, f"expected 3 hop-1 children, got {len(children)}"
        assert len(grandchildren) == 3, f"expected 3 hop-2 grandchildren, got {len(grandchildren)}"
        # Activation must be monotonic by hop (decay): every hop-1 score >= every hop-2 score.
        s1 = [r.get("score", 0) for r in env.results if r.get("hop_distance") == 1]
        s2 = [r.get("score", 0) for r in env.results if r.get("hop_distance") == 2]
        assert min(s1) >= max(s2), (
            "activation not monotonic by hop — decay/visited logic changed "
            f"(hop1 min {min(s1)} < hop2 max {max(s2)})"
        )
        conn.close()
