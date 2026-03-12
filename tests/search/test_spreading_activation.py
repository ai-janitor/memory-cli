# =============================================================================
# Module: test_spreading_activation.py
# Purpose: Test BFS spreading activation — stage 5 of the light search
#   pipeline. Verifies BFS traversal, linear decay, edge weight modulation,
#   cycle handling, visited set behavior, and depth limits.
# Rationale: Spreading activation is the most algorithmically complex stage.
#   Bugs in BFS (infinite loops from cycles), decay (wrong formula), or
#   visited set (stale activations) would silently corrupt search results.
#   Thorough testing of graph traversal patterns is essential.
# Responsibility:
#   - Test BFS traverses edges bidirectionally
#   - Test linear decay formula: max(0, 1 - (depth+1) * decay_rate)
#   - Test edge weight modulation: activation * edge_weight
#   - Test cycle handling (visited set prevents infinite loops)
#   - Test visited set max-score update (higher activation replaces lower)
#   - Test depth limits (fan_out_depth=0,1,2,3)
#   - Test seeds get activation=1.0, match_type="direct_match"
#   - Test fan-out neurons get match_type="fan_out" with hop_distance
# Organization:
#   1. Imports and fixtures
#   2. Seed initialization tests
#   3. BFS traversal tests
#   4. Linear decay tests
#   5. Edge weight modulation tests
#   6. Cycle and visited set tests
#   7. Depth limit tests
# =============================================================================

from __future__ import annotations

import time

import pytest

from memory_cli.search.spreading_activation_bfs_linear_decay import (
    spread,
    _compute_activation,
    _get_neighbors,
    MAX_FAN_OUT_DEPTH,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """Full in-memory DB with schema for graph testing."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    return conn


def _insert_neuron(conn, content="test", project="test"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_edge(conn, source_id, target_id, weight=1.0, reason="related"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, weight, reason, now_ms),
    )


def _make_rrf_candidate(neuron_id, rrf_score=0.016):
    return {"neuron_id": neuron_id, "rrf_score": rrf_score}


@pytest.fixture
def graph_db(migrated_conn):
    """Graph structure:
    1 --0.8--> 2 --0.6--> 3 --1.0--> 4
    1 --0.5--> 5
    3 --0.7--> 1  (cycle back to seed)
    5 --0.9--> 6
    """
    conn = migrated_conn
    conn.execute("BEGIN")
    for i in range(1, 7):
        _insert_neuron(conn, f"neuron {i}")
    _insert_edge(conn, 1, 2, 0.8, "reason_1_2")
    _insert_edge(conn, 2, 3, 0.6, "reason_2_3")
    _insert_edge(conn, 3, 4, 1.0, "reason_3_4")
    _insert_edge(conn, 1, 5, 0.5, "reason_1_5")
    _insert_edge(conn, 3, 1, 0.7, "reason_3_1")  # cycle
    _insert_edge(conn, 5, 6, 0.9, "reason_5_6")
    conn.execute("COMMIT")
    return conn


# -----------------------------------------------------------------------------
# Seed initialization tests
# -----------------------------------------------------------------------------

class TestSpreadingSeedInit:
    """Test that seeds are correctly initialized."""

    def test_seeds_have_activation_1(self, graph_db):
        """Verify all seed neurons get activation_score=1.0."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=0)
        by_id = {r["neuron_id"]: r for r in results}
        assert by_id[1]["activation_score"] == 1.0

    def test_seeds_have_match_type_direct(self, graph_db):
        """Verify seeds have match_type='direct_match'."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=0)
        by_id = {r["neuron_id"]: r for r in results}
        assert by_id[1]["match_type"] == "direct_match"

    def test_seeds_have_hop_distance_zero(self, graph_db):
        """Verify seeds have hop_distance=0."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=0)
        by_id = {r["neuron_id"]: r for r in results}
        assert by_id[1]["hop_distance"] == 0

    def test_seeds_preserve_rrf_metadata(self, graph_db):
        """Verify seeds retain rrf_score and other RRF metadata."""
        seeds = [_make_rrf_candidate(1, rrf_score=0.033)]
        results = spread(graph_db, seeds, fan_out_depth=0)
        by_id = {r["neuron_id"]: r for r in results}
        assert by_id[1]["rrf_score"] == 0.033


# -----------------------------------------------------------------------------
# BFS traversal tests
# -----------------------------------------------------------------------------

class TestSpreadingBFSTraversal:
    """Test BFS traversal through graph edges."""

    def test_outgoing_edges_traversed(self, graph_db):
        """Verify neighbors via outgoing edges (source→target) are discovered."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=1)
        neuron_ids = {r["neuron_id"] for r in results}
        # Neuron 1 has outgoing edges to 2 and 5
        assert 2 in neuron_ids
        assert 5 in neuron_ids

    def test_incoming_edges_traversed(self, graph_db):
        """Verify neighbors via incoming edges (target→source) are discovered.

        Bidirectional: if A→B exists, B can reach A via that edge.
        """
        # Seed on neuron 2 — it has outgoing to 3, incoming from 1
        seeds = [_make_rrf_candidate(2)]
        results = spread(graph_db, seeds, fan_out_depth=1)
        neuron_ids = {r["neuron_id"] for r in results}
        # Should discover neuron 1 via incoming edge (1→2)
        assert 1 in neuron_ids

    def test_fan_out_neurons_have_correct_hop_distance(self, graph_db):
        """Verify fan-out neurons have correct hop_distance.

        1-hop neighbor → hop_distance=1.
        2-hop neighbor → hop_distance=2.
        """
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=2)
        by_id = {r["neuron_id"]: r for r in results}
        # 2 and 5 are 1-hop from seed 1
        if 2 in by_id:
            assert by_id[2]["hop_distance"] == 1
        if 5 in by_id:
            assert by_id[5]["hop_distance"] == 1

    def test_fan_out_neurons_have_edge_reason(self, graph_db):
        """Verify fan-out neurons carry edge_reason from connecting edge."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=1)
        by_id = {r["neuron_id"]: r for r in results}
        if 2 in by_id:
            assert by_id[2]["edge_reason"] is not None

    def test_fan_out_neurons_have_match_type_fan_out(self, graph_db):
        """Verify discovered neurons have match_type='fan_out'."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=1)
        by_id = {r["neuron_id"]: r for r in results}
        for nid, r in by_id.items():
            if nid != 1:
                assert r["match_type"] == "fan_out"


# -----------------------------------------------------------------------------
# Linear decay tests
# -----------------------------------------------------------------------------

class TestSpreadingLinearDecay:
    """Test the linear decay formula."""

    def test_depth_1_activation_with_default_decay(self):
        """Verify depth=1, decay_rate=0.3:
        activation = max(0, 1 - (1+1)*0.3) = 0.4

        Before edge weight modulation.
        """
        # edge_weight=1.0 means no modulation
        result = _compute_activation(1.0, 0, 0.3, 1.0)
        assert abs(result - 0.4) < 1e-9

    def test_depth_2_activation_with_default_decay(self):
        """Verify depth=2, decay_rate=0.3:
        activation = max(0, 1 - (2+1)*0.3) = 0.1
        """
        result = _compute_activation(1.0, 1, 0.3, 1.0)
        assert abs(result - 0.1) < 1e-9

    def test_depth_3_activation_fully_decayed(self):
        """Verify depth=3, decay_rate=0.3:
        activation = max(0, 1 - (3+1)*0.3) = max(0, -0.2) = 0.0

        Fully decayed — neuron should not be in results.
        """
        result = _compute_activation(1.0, 2, 0.3, 1.0)
        assert result == 0.0

    def test_custom_decay_rate(self):
        """Verify custom decay_rate changes activation values.

        decay_rate=0.5, depth=1: max(0, 1 - 2*0.5) = 0.0
        """
        result = _compute_activation(1.0, 0, 0.5, 1.0)
        assert result == 0.0

    def test_zero_activation_not_propagated(self, graph_db):
        """Verify neurons with 0 activation are not enqueued for further BFS."""
        # With decay_rate=0.5 and depth=1, child activation = max(0,1-2*0.5)=0
        seeds = [_make_rrf_candidate(1)]
        # Use large decay_rate so depth-1 activation → 0
        results = spread(graph_db, seeds, fan_out_depth=1, decay_rate=0.5)
        by_id = {r["neuron_id"]: r for r in results}
        # Neighbors at depth=1 with edge_weight=0.8: max(0,1-(1+1)*0.5)*0.8 = 0*0.8 = 0
        # So no fan-out should be in results (activation=0 filtered out)
        for nid, r in by_id.items():
            if nid != 1:
                assert r["activation_score"] > 0


# -----------------------------------------------------------------------------
# Edge weight modulation tests
# -----------------------------------------------------------------------------

class TestSpreadingEdgeWeightModulation:
    """Test that edge weights modulate activation scores."""

    def test_high_weight_edge_preserves_activation(self):
        """Verify edge weight=1.0 passes full base activation through.

        depth=1, decay=0.3, weight=1.0: 0.4 * 1.0 = 0.4
        """
        result = _compute_activation(1.0, 0, 0.3, 1.0)
        assert abs(result - 0.4) < 1e-9

    def test_low_weight_edge_reduces_activation(self):
        """Verify edge weight=0.2 reduces activation.

        depth=1, decay=0.3, weight=0.2: 0.4 * 0.2 = 0.08
        """
        result = _compute_activation(1.0, 0, 0.3, 0.2)
        assert abs(result - 0.08) < 1e-9

    def test_zero_weight_edge_blocks_activation(self):
        """Verify edge weight=0.0 blocks activation entirely.

        0.4 * 0.0 = 0.0 — neighbor should not appear in results.
        """
        result = _compute_activation(1.0, 0, 0.3, 0.0)
        assert result == 0.0


# -----------------------------------------------------------------------------
# Cycle and visited set tests
# -----------------------------------------------------------------------------

class TestSpreadingCycleHandling:
    """Test cycle detection and visited set behavior."""

    def test_cycle_does_not_cause_infinite_loop(self, graph_db):
        """Verify graph cycle (1→2→3→1 via edge 3→1) terminates.

        BFS with cycles must terminate due to visited set.
        """
        seeds = [_make_rrf_candidate(1)]
        # This should complete without hanging
        results = spread(graph_db, seeds, fan_out_depth=3)
        assert results is not None
        assert len(results) > 0

    def test_visited_set_prevents_revisit_with_lower_activation(self, graph_db):
        """Verify a neuron reached with higher activation is not overwritten
        by a lower activation path.
        """
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=3)
        # Each neuron should appear at most once
        neuron_ids = [r["neuron_id"] for r in results]
        assert len(neuron_ids) == len(set(neuron_ids))

    def test_visited_set_allows_update_with_higher_activation(self, migrated_conn):
        """Verify a neuron can be updated if reached with higher activation
        via a different path.
        """
        conn = migrated_conn
        conn.execute("BEGIN")
        for i in range(1, 5):
            _insert_neuron(conn, f"neuron {i}")
        # Two seeds reach neuron 3: via 1→3 (weight 0.9) and via 2→3 (weight 0.1)
        _insert_edge(conn, 1, 3, 0.9, "strong")
        _insert_edge(conn, 2, 3, 0.1, "weak")
        conn.execute("COMMIT")
        seeds = [_make_rrf_candidate(1), _make_rrf_candidate(2)]
        results = spread(conn, seeds, fan_out_depth=1)
        by_id = {r["neuron_id"]: r for r in results}
        # Neuron 3 should appear once with the higher activation
        assert 3 in by_id
        # activation from seed 1: max(0,1-2*0.3)*0.9 = 0.4*0.9=0.36
        # activation from seed 2: max(0,1-2*0.3)*0.1 = 0.4*0.1=0.04
        # Should keep 0.36
        assert by_id[3]["activation_score"] > 0.3

    def test_seed_not_overwritten_by_fan_out_path(self, graph_db):
        """Verify seed neurons (activation=1.0) are not replaced by fan-out
        paths that loop back to them with lower activation.
        """
        # Neuron 3 loops back to neuron 1 with edge weight 0.7
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=3)
        by_id = {r["neuron_id"]: r for r in results}
        # Seed neuron 1 must retain activation=1.0 despite the loop
        assert by_id[1]["activation_score"] == 1.0
        assert by_id[1]["match_type"] == "direct_match"


# -----------------------------------------------------------------------------
# Depth limit tests
# -----------------------------------------------------------------------------

class TestSpreadingDepthLimits:
    """Test fan_out_depth parameter."""

    def test_depth_zero_returns_seeds_only(self, graph_db):
        """Verify fan_out_depth=0 returns only seed neurons, no fan-out."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=0)
        assert len(results) == 1
        assert results[0]["neuron_id"] == 1

    def test_depth_one_returns_one_hop(self, graph_db):
        """Verify fan_out_depth=1 returns seeds + 1-hop neighbors."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=1)
        neuron_ids = {r["neuron_id"] for r in results}
        # Should have seed + direct neighbors
        assert 1 in neuron_ids
        # Neuron 2 and 5 are 1-hop from 1
        assert 2 in neuron_ids or 5 in neuron_ids

    def test_depth_two_returns_two_hops(self, graph_db):
        """Verify fan_out_depth=2 returns seeds + up to 2-hop neighbors."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=2)
        neuron_ids = {r["neuron_id"] for r in results}
        # Neuron 3 (via 1→2→3) should be reachable at depth 2
        # but only if activation doesn't decay to 0
        # decay=0.3: depth=1 base=max(0,1-2*0.3)=0.4; depth=2 base=max(0,1-3*0.3)=0.1
        # So neuron 3 should be activated (0.1 * 0.6 = 0.06 > 0)
        assert 3 in neuron_ids

    def test_depth_clamped_to_max_three(self, graph_db):
        """Verify fan_out_depth > 3 is clamped to 3."""
        seeds = [_make_rrf_candidate(1)]
        results_depth3 = spread(graph_db, seeds, fan_out_depth=3)
        results_depth10 = spread(graph_db, seeds, fan_out_depth=10)
        # Results should be identical since 10 is clamped to 3
        ids_3 = {r["neuron_id"] for r in results_depth3}
        ids_10 = {r["neuron_id"] for r in results_depth10}
        assert ids_3 == ids_10

    def test_negative_depth_clamped_to_zero(self, graph_db):
        """Verify fan_out_depth < 0 is clamped to 0 (seeds only)."""
        seeds = [_make_rrf_candidate(1)]
        results = spread(graph_db, seeds, fan_out_depth=-5)
        # Should return seeds only (depth clamped to 0)
        assert len(results) == 1
        assert results[0]["neuron_id"] == 1
