# =============================================================================
# Module: test_edge_list.py
# Purpose: Test edge listing via edge_list() — direction filters (outgoing,
#   incoming, both), pagination (limit/offset), empty results, and content
#   snippet generation for connected neurons.
# Rationale: Edge listing is the primary graph exploration query. Tests must
#   cover all three direction modes, verify correct connected neuron
#   identification (outgoing -> target, incoming -> source), check that
#   snippets are properly truncated, and confirm pagination math.
# Responsibility:
#   - Test outgoing filter: returns edges where anchor is source
#   - Test incoming filter: returns edges where anchor is target
#   - Test both filter: returns union of outgoing + incoming
#   - Test default direction is outgoing
#   - Test neuron not found -> exit 1
#   - Test invalid direction -> exit 2
#   - Test empty result returns empty list (not an error)
#   - Test pagination with limit and offset
#   - Test ordering by created_at DESC
#   - Test content snippets truncated to ~100 chars
#   - Test snippet for short content (no truncation needed)
#   - Test connected_neuron_id is correct for each direction
# Organization:
#   1. Imports and fixtures
#   2. TestEdgeListDirection — direction filter tests
#   3. TestEdgeListPagination — limit/offset tests
#   4. TestEdgeListSnippets — content truncation tests
#   5. TestEdgeListErrors — validation error paths
#   6. TestEdgeListEmpty — empty result scenarios
# =============================================================================

from __future__ import annotations

import time

import pytest
from typing import Any, Dict, List

# --- Module-level guard: all tests in this file require sqlite_vec ---
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _create_test_neuron(conn, content="test content", project="test-project"):
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
        (content, now_ms, now_ms, project)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _create_test_edge(conn, source_id, target_id, reason="test-link", weight=1.0, created_at=None):
    if created_at is None:
        created_at = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, reason, weight, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, reason, weight, created_at)
    )


@pytest.fixture
def graph_conn(migrated_conn):
    """Create a small graph topology for testing:

    Neuron 1 (content="Alpha neuron with short content")
    Neuron 2 (content="Beta neuron with short content")
    Neuron 3 (content="Gamma neuron with a much longer content string that
               exceeds one hundred characters so we can test snippet truncation
               behavior in the edge list output here")
    Neuron 4 (content="Delta neuron isolated no edges")

    Edges:
      1 -> 2 (reason="alpha-to-beta", weight=1.0, created_at=1000)
      1 -> 3 (reason="alpha-to-gamma", weight=2.0, created_at=2000)
      2 -> 1 (reason="beta-to-alpha", weight=1.0, created_at=3000)
      3 -> 3 (self-loop, reason="gamma-self", weight=0.5, created_at=4000)
    """
    conn = migrated_conn

    # Create neurons with fixed IDs via direct insert
    now_ms = int(time.time() * 1000)
    long_content = (
        "Gamma neuron with a much longer content string that exceeds one hundred "
        "characters so we can test snippet truncation behavior in the edge list output here"
    )

    neuron_ids = []
    for content in [
        "Alpha neuron with short content",
        "Beta neuron with short content",
        long_content,
        "Delta neuron isolated no edges",
    ]:
        conn.execute(
            "INSERT INTO neurons (content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, 'active')",
            (content, now_ms, now_ms, "test-project")
        )
        neuron_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    n1, n2, n3, n4 = neuron_ids

    _create_test_edge(conn, n1, n2, "alpha-to-beta", weight=1.0, created_at=1000)
    _create_test_edge(conn, n1, n3, "alpha-to-gamma", weight=2.0, created_at=2000)
    _create_test_edge(conn, n2, n1, "beta-to-alpha", weight=1.0, created_at=3000)
    _create_test_edge(conn, n3, n3, "gamma-self", weight=0.5, created_at=4000)

    return conn, n1, n2, n3, n4


# -----------------------------------------------------------------------------
# Direction filter tests
# -----------------------------------------------------------------------------

class TestEdgeListDirection:
    """Test direction filter behavior (outgoing, incoming, both)."""

    def test_outgoing_returns_source_edges(self, graph_conn):
        """List outgoing edges for neuron 1.

        Expects:
        - Returns edges 1->2 and 1->3
        - connected_neuron_id is 2 and 3 respectively (targets)
        - Does NOT include edge 2->1 (that's incoming, not outgoing)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing")

        assert len(results) == 2
        connected_ids = {r["connected_neuron_id"] for r in results}
        assert n2 in connected_ids
        assert n3 in connected_ids
        # All results have source_id == n1 (outgoing from n1)
        for r in results:
            assert r["source_id"] == n1

    def test_incoming_returns_target_edges(self, graph_conn):
        """List incoming edges for neuron 1.

        Expects:
        - Returns edge 2->1
        - connected_neuron_id is 2 (the source)
        - Does NOT include edges 1->2 or 1->3 (those are outgoing)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="incoming")

        assert len(results) == 1
        assert results[0]["connected_neuron_id"] == n2
        assert results[0]["target_id"] == n1

    def test_both_returns_union(self, graph_conn):
        """List both directions for neuron 1.

        Expects:
        - Returns edges 1->2, 1->3, AND 2->1
        - All three edges present
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="both")

        assert len(results) == 3
        reasons = {r["reason"] for r in results}
        assert "alpha-to-beta" in reasons
        assert "alpha-to-gamma" in reasons
        assert "beta-to-alpha" in reasons

    def test_default_direction_is_outgoing(self, graph_conn):
        """Calling edge_list without --direction defaults to outgoing.

        Expects: same results as explicit direction="outgoing"
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        default_results = edge_list(conn, n1)
        outgoing_results = edge_list(conn, n1, direction="outgoing")

        assert len(default_results) == len(outgoing_results)
        default_reasons = {r["reason"] for r in default_results}
        outgoing_reasons = {r["reason"] for r in outgoing_results}
        assert default_reasons == outgoing_reasons

    def test_self_loop_in_both_directions(self, graph_conn):
        """Self-loop edge appears in both outgoing and incoming for same neuron.

        List edges for neuron 3 with direction="both".
        Expects:
        - Self-loop 3->3 appears (possibly twice in UNION ALL)
        - connected_neuron_id is 3 (itself)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n3, direction="both")

        # n3 has: outgoing self-loop (3->3), incoming from 1->3, incoming self-loop (3->3)
        assert len(results) >= 2
        self_loop_results = [r for r in results if r["source_id"] == n3 and r["target_id"] == n3]
        assert len(self_loop_results) >= 1  # self-loop appears in both directions

    def test_ordering_by_created_at_desc(self, graph_conn):
        """Edges are ordered by created_at DESC (newest first).

        List outgoing for neuron 1.
        Expects: 1->3 (created_at=2000) before 1->2 (created_at=1000)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing")

        assert len(results) == 2
        # First result has higher created_at (newest first)
        assert results[0]["created_at"] >= results[1]["created_at"]
        # Specifically: alpha-to-gamma (created_at=2000) should come before alpha-to-beta (created_at=1000)
        assert results[0]["reason"] == "alpha-to-gamma"
        assert results[1]["reason"] == "alpha-to-beta"


# -----------------------------------------------------------------------------
# Pagination tests
# -----------------------------------------------------------------------------

class TestEdgeListPagination:
    """Test limit and offset pagination."""

    def test_limit_restricts_results(self, graph_conn):
        """Limit=1 returns only the first (newest) edge.

        List outgoing for neuron 1 with limit=1.
        Expects: only 1 edge returned (the newest one by created_at)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing", limit=1)

        assert len(results) == 1
        # Newest edge: alpha-to-gamma (created_at=2000)
        assert results[0]["reason"] == "alpha-to-gamma"

    def test_offset_skips_results(self, graph_conn):
        """Offset=1 skips the first result.

        List outgoing for neuron 1 with offset=1.
        Expects: 1 edge returned (the older one, since newest was skipped)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing", offset=1)

        assert len(results) == 1
        # After skipping newest (alpha-to-gamma), we get alpha-to-beta
        assert results[0]["reason"] == "alpha-to-beta"

    def test_limit_and_offset_combined(self, graph_conn):
        """Limit + offset for page 2.

        List outgoing for neuron 1 with limit=1, offset=1.
        Expects: 1 edge returned (the second-newest)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing", limit=1, offset=1)

        assert len(results) == 1
        assert results[0]["reason"] == "alpha-to-beta"

    def test_offset_beyond_results(self, graph_conn):
        """Offset larger than total results returns empty list.

        List outgoing for neuron 1 with offset=100.
        Expects: empty list (not an error)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing", offset=100)

        assert results == []


# -----------------------------------------------------------------------------
# Snippet tests
# -----------------------------------------------------------------------------

class TestEdgeListSnippets:
    """Test content snippet truncation for connected neurons."""

    def test_short_content_no_truncation(self, graph_conn):
        """Content under 100 chars is returned as-is.

        List outgoing edges from n1 to n2 (short content).
        Expects: connected_neuron_snippet == full content of neuron 2
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing")

        # Find the edge going to n2
        edge_to_n2 = next(r for r in results if r["target_id"] == n2)
        assert edge_to_n2["connected_neuron_snippet"] == "Beta neuron with short content"
        assert not edge_to_n2["connected_neuron_snippet"].endswith("...")

    def test_long_content_truncated_with_ellipsis(self, graph_conn):
        """Content over 100 chars is truncated with "..." suffix.

        List outgoing edges from n1 to n3 (long content).
        Expects:
        - connected_neuron_snippet ends with "..."
        - Snippet starts with the beginning of neuron 3's content
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="outgoing")

        # Find the edge going to n3
        edge_to_n3 = next(r for r in results if r["target_id"] == n3)
        snippet = edge_to_n3["connected_neuron_snippet"]

        assert snippet.endswith("...")
        assert snippet.startswith("Gamma neuron")
        # Length should be 103 (100 chars + "...")
        assert len(snippet) == 103

    def test_snippet_field_present_in_all_results(self, graph_conn):
        """Every edge dict in results has connected_neuron_snippet key.

        Expects: all result dicts contain 'connected_neuron_snippet'
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n1, direction="both")

        for r in results:
            assert "connected_neuron_snippet" in r
            assert isinstance(r["connected_neuron_snippet"], str)


# -----------------------------------------------------------------------------
# Error tests
# -----------------------------------------------------------------------------

class TestEdgeListErrors:
    """Test validation error paths."""

    def test_neuron_not_found_exit_1(self, migrated_conn):
        """List edges for a non-existent neuron ID.

        Expects:
        - EdgeListError raised
        - exit_code == 1
        - Message mentions the neuron ID
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list, EdgeListError

        nonexistent_id = 99999

        with pytest.raises(EdgeListError) as exc_info:
            edge_list(migrated_conn, nonexistent_id)

        assert exc_info.value.exit_code == 1
        assert str(nonexistent_id) in str(exc_info.value)

    def test_invalid_direction_exit_2(self, migrated_conn):
        """Pass an invalid direction string.

        Expects:
        - EdgeListError raised
        - exit_code == 2
        - Message mentions valid direction options
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list, EdgeListError

        n = _create_test_neuron(migrated_conn)

        with pytest.raises(EdgeListError) as exc_info:
            edge_list(migrated_conn, n, direction="sideways")

        assert exc_info.value.exit_code == 2
        assert "sideways" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# Empty result tests
# -----------------------------------------------------------------------------

class TestEdgeListEmpty:
    """Test empty result scenarios — all should return empty list, not error."""

    def test_neuron_with_no_edges(self, graph_conn):
        """List edges for neuron 4 (isolated, no edges).

        Expects: empty list, no exception
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        conn, n1, n2, n3, n4 = graph_conn
        results = edge_list(conn, n4)

        assert results == []

    def test_neuron_with_no_outgoing(self, migrated_conn):
        """Neuron has only incoming edges, list outgoing.

        Expects: empty list (neuron exists but has no outgoing edges)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        src = _create_test_neuron(migrated_conn, "source")
        tgt = _create_test_neuron(migrated_conn, "target with no outgoing")
        _create_test_edge(migrated_conn, src, tgt, "only incoming for tgt")

        results = edge_list(migrated_conn, tgt, direction="outgoing")

        assert results == []

    def test_neuron_with_no_incoming(self, migrated_conn):
        """Neuron has only outgoing edges, list incoming.

        Expects: empty list (neuron exists but has no incoming edges)
        """
        from memory_cli.edge.edge_list_by_neuron_direction import edge_list

        src = _create_test_neuron(migrated_conn, "source with no incoming")
        tgt = _create_test_neuron(migrated_conn, "target")
        _create_test_edge(migrated_conn, src, tgt, "only outgoing for src")

        results = edge_list(migrated_conn, src, direction="incoming")

        assert results == []
